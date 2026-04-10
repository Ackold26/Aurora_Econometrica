use anyhow::{Context, Result};
use log::{debug, info, warn};
use std::path::{Path, PathBuf};
use std::process::Stdio;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Find the pptx_pipeline executable or script.
/// In dev: python + sidecar/pptx_pipeline.py
/// In release: bundled pptx_pipeline.exe
fn find_pipeline() -> Result<(String, Vec<String>)> {
    // Release: look for bundled exe next to the app binary
    if !cfg!(debug_assertions) {
        if let Ok(exe) = std::env::current_exe() {
            let dir = exe.parent().unwrap_or(Path::new("."));
            let pipeline_exe = dir.join("pptx_pipeline.exe");
            if pipeline_exe.exists() {
                return Ok((pipeline_exe.to_string_lossy().to_string(), vec![]));
            }
        }
    }

    // Dev: use python + script path
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR")
        .unwrap_or_else(|_| ".".to_string());
    let script = PathBuf::from(&manifest_dir)
        .join("sidecar")
        .join("pptx_pipeline.py");

    if script.exists() {
        let python = if cfg!(windows) { "python" } else { "python3" };
        Ok((python.to_string(), vec![script.to_string_lossy().to_string()]))
    } else {
        anyhow::bail!("pptx_pipeline not found (checked exe and dev script at {})", script.display())
    }
}

/// Pipeline timeout — kill process if it takes longer than this.
const PIPELINE_TIMEOUT_SECS: u64 = 60;

/// Run the pipeline with given mode and args. Returns stdout as String.
/// Kills the subprocess if it exceeds PIPELINE_TIMEOUT_SECS.
fn run_pipeline(mode: &str, args: &[&str]) -> Result<String> {
    let (cmd, mut prefix_args) = find_pipeline()?;
    prefix_args.push(mode.to_string());
    prefix_args.extend(args.iter().map(|a| a.to_string()));

    debug!("pptx_pipeline: {} {:?}", cmd, prefix_args);

    #[cfg(windows)]
    let child = {
        std::process::Command::new("cmd")
            .arg("/C")
            .arg(&cmd)
            .args(&prefix_args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .spawn()
            .context("Failed to spawn pptx_pipeline")?
    };

    #[cfg(not(windows))]
    let child = {
        std::process::Command::new(&cmd)
            .args(&prefix_args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .context("Failed to spawn pptx_pipeline")?
    };

    // Wait with timeout — prevent hanging process from blocking the app
    let pid = child.id();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(child.wait_with_output());
    });

    let output = match rx.recv_timeout(std::time::Duration::from_secs(PIPELINE_TIMEOUT_SECS)) {
        Ok(result) => result.context("Failed to run pptx_pipeline")?,
        Err(_) => {
            log::warn!("pptx_pipeline {mode} timed out after {PIPELINE_TIMEOUT_SECS}s, killing PID {pid}");
            #[cfg(windows)]
            {
                let _ = std::process::Command::new("taskkill")
                    .args(["/F", "/T", "/PID", &pid.to_string()])
                    .creation_flags(0x08000000)
                    .output();
            }
            #[cfg(not(windows))]
            {
                unsafe { libc::kill(pid as i32, libc::SIGKILL); }
            }
            anyhow::bail!("pptx_pipeline {mode} timed out after {PIPELINE_TIMEOUT_SECS}s");
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("pptx_pipeline {mode} failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    Ok(stdout)
}

/// Preprocess a PPTX file: extract text, chart data, styles into JSON.
/// Returns the path to slides.json.
pub fn preprocess(pptx_path: &Path, output_dir: &Path) -> Result<PathBuf> {
    let file_size = std::fs::metadata(pptx_path).map(|m| m.len()).unwrap_or(0);
    info!("PPTX preprocess: {} ({} KB) → {}", pptx_path.display(), file_size / 1024, output_dir.display());

    std::fs::create_dir_all(output_dir)?;

    let result = run_pipeline("preprocess", &[
        &pptx_path.to_string_lossy(),
        &output_dir.to_string_lossy(),
    ])?;

    // Parse stdout JSON to verify success
    match serde_json::from_str::<serde_json::Value>(&result) {
        Ok(json) => {
            if json["status"] == "ok" {
                let slides = json["data_slides"].as_u64().unwrap_or(0);
                let charts = json["charts"].as_u64().unwrap_or(0);
                info!("PPTX preprocessed: {slides} data slides, {charts} charts");
            }
        }
        Err(e) => {
            let preview = &result[..result.len().min(200)];
            warn!("PPTX preprocess: unexpected output (JSON parse error: {e}): {preview}");
        }
    }

    let slides_json = output_dir.join("slides.json");
    if !slides_json.exists() {
        anyhow::bail!("preprocess did not create slides.json");
    }

    Ok(slides_json)
}

/// Inject commentary notes into PPTX slides' notes pane.
pub fn inject_notes(pptx_path: &Path, notes_json: &Path, output_path: &Path) -> Result<()> {
    info!("PPTX inject notes: {} + {} → {}", pptx_path.display(), notes_json.display(), output_path.display());

    let result = run_pipeline("inject-notes", &[
        &pptx_path.to_string_lossy(),
        &notes_json.to_string_lossy(),
        &output_path.to_string_lossy(),
    ])?;

    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&result) {
        let updated = json["slides_updated"].as_u64().unwrap_or(0);
        info!("PPTX notes injected: {updated} slides");
    }

    Ok(())
}

/// Generate a formatted DOCX from PPTX + commentary notes.
pub fn generate_docx(pptx_path: &Path, notes_json: &Path, styles_json: &Path, output_path: &Path) -> Result<()> {
    info!("PPTX generate docx: {} → {}", pptx_path.display(), output_path.display());

    let result = run_pipeline("generate-docx", &[
        &pptx_path.to_string_lossy(),
        &notes_json.to_string_lossy(),
        &styles_json.to_string_lossy(),
        &output_path.to_string_lossy(),
    ])?;

    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&result) {
        let documented = json["slides_documented"].as_u64().unwrap_or(0);
        info!("DOCX generated: {documented} slides documented");
    }

    Ok(())
}

/// Parse Claude's markdown response into structured notes for each slide.
/// Expects markdown with `## Slide N: ...` or `## Слайд N: ...` headings.
/// Also matches `### Слайд N`, `## Слайд №N`, `## N. Title`.
pub fn parse_response_to_notes(response: &str) -> Vec<serde_json::Value> {
    use std::sync::OnceLock;
    static SLIDE_RE: OnceLock<regex::Regex> = OnceLock::new();
    let slide_re = SLIDE_RE.get_or_init(|| {
        regex::Regex::new(r"(?i)^#{2,3}\s*(?:(?:slide|слайд)\s*№?\s*(\d+)|(\d+)\.\s)").unwrap()
    });

    let mut notes = Vec::new();
    let mut current_slide: Option<u32> = None;
    let mut current_text = String::new();

    for line in response.lines() {
        if let Some(caps) = slide_re.captures(line) {
            // Save previous slide
            if let Some(num) = current_slide {
                if !current_text.trim().is_empty() {
                    notes.push(serde_json::json!({
                        "slide_num": num,
                        "text": current_text.trim(),
                    }));
                }
            }
            // Match group 1 (## Слайд N) or group 2 (## N. Title)
            current_slide = caps.get(1)
                .or_else(|| caps.get(2))
                .and_then(|m| m.as_str().parse().ok());
            current_text.clear();
        } else if current_slide.is_some() {
            current_text.push_str(line);
            current_text.push('\n');
        }
    }

    // Last slide
    if let Some(num) = current_slide {
        if !current_text.trim().is_empty() {
            notes.push(serde_json::json!({
                "slide_num": num,
                "text": current_text.trim(),
            }));
        }
    }

    notes
}

/// Generate a formatted DOCX with synthesis prefix (Executive Summary, blocks, bridges).
pub fn generate_docx_with_synthesis(
    pptx_path: &Path, notes_json: &Path, styles_json: &Path,
    synthesis_md: &Path, output_path: &Path,
) -> Result<()> {
    info!("PPTX generate docx with synthesis: {} → {}", pptx_path.display(), output_path.display());

    let result = run_pipeline("generate-docx-with-synthesis", &[
        &pptx_path.to_string_lossy(),
        &notes_json.to_string_lossy(),
        &styles_json.to_string_lossy(),
        &synthesis_md.to_string_lossy(),
        &output_path.to_string_lossy(),
    ])?;

    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&result) {
        let documented = json["slides_documented"].as_u64().unwrap_or(0);
        let has_synthesis = json["has_synthesis"].as_bool().unwrap_or(false);
        info!("DOCX generated: {documented} slides, synthesis={has_synthesis}");
    }

    Ok(())
}

/// Split a full analytics response into slide notes + synthesis sections.
/// Slide notes = everything under `## Слайд N:` headers.
/// Synthesis = everything under `## EXECUTIVE SUMMARY`, `## БЛОК:`, `## МОСТЫ`, `## РЕКОМЕНДАЦИИ`.
pub fn split_response_notes_and_synthesis(response: &str) -> (String, String) {
    let synthesis_prefixes = [
        "## EXECUTIVE SUMMARY", "## ОБЩИЙ ВЫВОД", "## БЛОК:", "## МОСТЫ", "## РЕКОМЕНДАЦИИ",
        "# EXECUTIVE SUMMARY", "# ОБЩИЙ ВЫВОД", "# БЛОК:", "# МОСТЫ", "# РЕКОМЕНДАЦИИ",
    ];

    let mut notes_lines: Vec<&str> = Vec::new();
    let mut synthesis_lines: Vec<&str> = Vec::new();
    let mut in_synthesis = false;

    for line in response.lines() {
        let trimmed = line.trim();

        // Check if this line starts a synthesis section
        let is_synthesis_header = synthesis_prefixes.iter().any(|p| {
            trimmed.to_uppercase().starts_with(&p.to_uppercase())
        });

        // Check if this line starts a slide section
        let is_slide_header = {
            use std::sync::OnceLock;
            static RE: OnceLock<regex::Regex> = OnceLock::new();
            let re = RE.get_or_init(|| {
                regex::Regex::new(r"(?i)^#{2,3}\s*(?:(?:slide|слайд)\s*№?\s*\d+|\d+\.\s)").unwrap()
            });
            re.is_match(trimmed)
        };

        if is_synthesis_header {
            in_synthesis = true;
        } else if is_slide_header {
            in_synthesis = false;
        }

        if in_synthesis {
            synthesis_lines.push(line);
        } else {
            notes_lines.push(line);
        }
    }

    (notes_lines.join("\n"), synthesis_lines.join("\n"))
}

// ─── Pipeline v2: Multi-phase analytics ────────────────────────────────

/// Chunk metadata for multi-phase pipeline.
pub struct ChunkSplit {
    pub data_slide_count: usize,
    pub chunk_count: usize,
    /// Paths to chunk JSON files in preprocessed/ directory.
    pub chunk_files: Vec<PathBuf>,
}

/// Generate a compact one-line-per-slide overview for Phase 0 (map).
/// Input: parsed slides.json array. Output: text to inject into Claude prompt.
pub fn generate_overview(slides: &[serde_json::Value]) -> String {
    let total = slides.len();
    let data_count = slides.iter().filter(|s| s["type"] == "data").count();
    let mut out = format!("[ОБЗОР ПРЕЗЕНТАЦИИ: {} слайдов, {} с данными]\n", total, data_count);

    for slide in slides {
        let num = slide["slide_num"].as_u64().unwrap_or(0);
        let title = slide["title"].as_str().unwrap_or("—");
        let stype = slide["type"].as_str().unwrap_or("unknown");
        let source = slide.get("source").and_then(|v| v.as_str());

        out.push_str(&format!("{}. \"{}\" [{}]", num, title, stype));
        if let Some(src) = source {
            out.push_str(&format!(" source={}", src));
        }
        // Indicate chart/table presence for map context
        let charts = slide.get("charts").and_then(|v| v.as_array()).map_or(0, |a| a.len());
        let tables = slide.get("tables").and_then(|v| v.as_array()).map_or(0, |a| a.len());
        if charts > 0 { out.push_str(&format!(" charts={}", charts)); }
        if tables > 0 { out.push_str(&format!(" tables={}", tables)); }
        out.push('\n');
    }
    out
}

/// Split data slides into chunk files by cumulative JSON byte size.
/// Non-data slides are excluded. Returns ChunkSplit with file paths.
pub fn split_into_chunks(
    slides: &[serde_json::Value],
    output_dir: &Path,
    max_chunk_bytes: usize,
) -> Result<ChunkSplit> {
    let data_slides: Vec<&serde_json::Value> = slides
        .iter()
        .filter(|s| s["type"] == "data")
        .collect();

    if data_slides.is_empty() {
        anyhow::bail!("No data slides found for chunking");
    }

    std::fs::create_dir_all(output_dir)?;

    let mut chunks: Vec<Vec<&serde_json::Value>> = Vec::new();
    let mut current_chunk: Vec<&serde_json::Value> = Vec::new();
    let mut current_bytes: usize = 0;

    for slide in &data_slides {
        let slide_json = serde_json::to_string(slide)?;
        let slide_bytes = slide_json.len();

        // If adding this slide exceeds limit and chunk is not empty, start new chunk
        if current_bytes + slide_bytes > max_chunk_bytes && !current_chunk.is_empty() {
            chunks.push(std::mem::take(&mut current_chunk));
            current_bytes = 0;
        }
        current_chunk.push(slide);
        current_bytes += slide_bytes;
    }
    if !current_chunk.is_empty() {
        chunks.push(current_chunk);
    }

    // Write chunk files
    let mut chunk_files = Vec::new();
    for (i, chunk) in chunks.iter().enumerate() {
        let filename = format!("chunk_{:03}.json", i + 1);
        let path = output_dir.join(&filename);
        let json_str = serde_json::to_string_pretty(chunk)?;
        std::fs::write(&path, &json_str)?;
        chunk_files.push(path);
    }

    Ok(ChunkSplit {
        data_slide_count: data_slides.len(),
        chunk_count: chunks.len(),
        chunk_files,
    })
}

/// Merge Phase 1 chunk markdowns into a single notes list.
/// Only parses `## Слайд N:` headers. Phase 2 (synthesis) is NOT included.
pub fn merge_chunk_notes(chunk_markdowns: &[String]) -> Vec<serde_json::Value> {
    let mut all_notes: std::collections::HashMap<u32, serde_json::Value> = std::collections::HashMap::new();

    for md in chunk_markdowns {
        let notes = parse_response_to_notes(md);
        for note in notes {
            if let Some(num) = note["slide_num"].as_u64() {
                all_notes.insert(num as u32, note);
            }
        }
    }

    let mut sorted: Vec<_> = all_notes.into_values().collect();
    sorted.sort_by_key(|n| n["slide_num"].as_u64().unwrap_or(0));

    // Log gaps in slide numbering (might indicate missed slides)
    if sorted.len() >= 2 {
        let nums: Vec<u64> = sorted.iter().filter_map(|n| n["slide_num"].as_u64()).collect();
        for w in nums.windows(2) {
            if w[1] - w[0] > 1 {
                debug!("merge_chunk_notes: gap in slide numbers: {} → {} (slides {}-{} missing)", w[0], w[1], w[0] + 1, w[1] - 1);
            }
        }
    }

    sorted
}

/// Generate compact recap of completed chunks for Phase 2 synthesis prompt.
/// ~3 lines per chunk: slide range + key findings extracted from ACTION TITLEs.
pub fn generate_recap(chunk_markdowns: &[String]) -> String {
    // Pre-allocate ~200 bytes per chunk to avoid quadratic reallocation
    let mut recap = String::with_capacity(200 * chunk_markdowns.len() + 64);
    recap.push_str("КРАТКИЙ ОБЗОР ПРОАНАЛИЗИРОВАННЫХ ЧАНКОВ:\n\n");

    for (i, md) in chunk_markdowns.iter().enumerate() {
        let notes = parse_response_to_notes(md);
        if notes.is_empty() {
            recap.push_str(&format!("Чанк {}: (нет данных)\n\n", i + 1));
            continue;
        }

        let first = notes.first().and_then(|n| n["slide_num"].as_u64()).unwrap_or(0);
        let last = notes.last().and_then(|n| n["slide_num"].as_u64()).unwrap_or(0);
        recap.push_str(&format!("Чанк {} (слайды {}-{}): ", i + 1, first, last));

        // Extract ACTION TITLEs as key findings
        let mut titles: Vec<String> = Vec::new();
        for note in &notes {
            if let Some(text) = note["text"].as_str() {
                for line in text.lines() {
                    if line.starts_with("ACTION TITLE:") {
                        let title = line.trim_start_matches("ACTION TITLE:").trim();
                        if !title.is_empty() && titles.len() < 3 {
                            titles.push(title.to_string());
                        }
                    }
                }
            }
        }

        if titles.is_empty() {
            recap.push_str(&format!("{} слайдов проанализировано\n", notes.len()));
        } else {
            recap.push_str(&titles.join("; "));
            recap.push('\n');
        }
        recap.push('\n');
    }
    recap
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_response_basic() {
        let response = r#"# Analysis
## Слайд 4: Динамика инвестиций
ACTION TITLE: Рост +34%
[CEO] Бюджет увеличился
[CMO] Digital превзошёл ТВ

## Слайд 5: Медиамикс
ACTION TITLE: Digital лидирует
[CEO] Перераспределить бюджет
"#;
        let notes = parse_response_to_notes(response);
        assert_eq!(notes.len(), 2);
        assert_eq!(notes[0]["slide_num"], 4);
        assert!(notes[0]["text"].as_str().unwrap().contains("ACTION TITLE"));
        assert_eq!(notes[1]["slide_num"], 5);
    }

    #[test]
    fn parse_response_empty() {
        let notes = parse_response_to_notes("Just some text without slide headers");
        assert!(notes.is_empty());
    }

    #[test]
    fn parse_response_h3_and_number_prefix() {
        let response = "### Слайд №4: Test\nContent A\n\n## 5. Another slide\nContent B\n";
        let notes = parse_response_to_notes(response);
        assert_eq!(notes.len(), 2);
        assert_eq!(notes[0]["slide_num"], 4);
        assert_eq!(notes[1]["slide_num"], 5);
    }

    // ─── Pipeline v2 tests ─────────────────────────────────────

    fn sample_slides() -> Vec<serde_json::Value> {
        (1..=10).map(|i| {
            serde_json::json!({
                "slide_num": i,
                "title": format!("Slide {}", i),
                "type": if i <= 2 { "title" } else { "data" },
                "texts": [format!("Text for slide {}", i)],
                "source": if i == 4 { serde_json::json!("Mediascope") } else { serde_json::Value::Null },
                "charts": if i % 3 == 0 { vec![serde_json::json!({"chart_type": "BAR"})] } else { vec![] },
            })
        }).collect()
    }

    #[test]
    fn generate_overview_basic() {
        let slides = sample_slides();
        let overview = generate_overview(&slides);
        assert!(overview.contains("[ОБЗОР ПРЕЗЕНТАЦИИ: 10 слайдов, 8 с данными]"));
        assert!(overview.contains("1. \"Slide 1\" [title]"));
        assert!(overview.contains("4. \"Slide 4\" [data] source=Mediascope"));
        assert!(overview.contains("charts=1")); // slide 3, 6, 9
    }

    #[test]
    fn split_into_chunks_basic() {
        let slides = sample_slides();
        let tmp = tempfile::tempdir().unwrap();
        let result = split_into_chunks(&slides, tmp.path(), 500).unwrap();
        assert_eq!(result.data_slide_count, 8); // slides 3-10
        assert!(result.chunk_count >= 2); // 8 data slides at 500 bytes max → multiple chunks
        for f in &result.chunk_files {
            assert!(f.exists());
        }
    }

    #[test]
    fn split_into_chunks_single() {
        let slides = sample_slides();
        let tmp = tempfile::tempdir().unwrap();
        // Very large max → single chunk
        let result = split_into_chunks(&slides, tmp.path(), 1_000_000).unwrap();
        assert_eq!(result.chunk_count, 1);
    }

    #[test]
    fn merge_chunk_notes_dedup() {
        let chunk1 = "## Слайд 4: A\nACTION TITLE: X\n[CEO] ...\n\n## Слайд 5: B\nACTION TITLE: Y\n".to_string();
        let chunk2 = "## Слайд 6: C\nACTION TITLE: Z\n\n## Слайд 5: B updated\nACTION TITLE: Y2\n".to_string();
        let notes = merge_chunk_notes(&[chunk1, chunk2]);
        assert_eq!(notes.len(), 3); // slides 4, 5, 6
        // Slide 5 from chunk2 wins (later overwrite)
        let slide5 = notes.iter().find(|n| n["slide_num"] == 5).unwrap();
        assert!(slide5["text"].as_str().unwrap().contains("Y2"));
    }

    #[test]
    fn split_notes_and_synthesis() {
        let response = r#"## Слайд 4: Инвестиции
ACTION TITLE: Рост +34%
[CEO] Бюджет увеличился

## Слайд 5: Медиа
ACTION TITLE: Digital лидирует

## EXECUTIVE SUMMARY
1. Рынок растёт
2. Digital лидирует

## БЛОК: Инвестиции — слайды 4-5
Бюджеты выросли на 34%.

## МОСТЫ
1. Рост инвестиций → рост digital

## РЕКОМЕНДАЦИИ
1. Увеличить digital-бюджет
"#;
        let (notes, synthesis) = split_response_notes_and_synthesis(response);
        assert!(notes.contains("## Слайд 4"));
        assert!(notes.contains("## Слайд 5"));
        assert!(!notes.contains("EXECUTIVE SUMMARY"));
        assert!(synthesis.contains("EXECUTIVE SUMMARY"));
        assert!(synthesis.contains("БЛОК: Инвестиции"));
        assert!(synthesis.contains("МОСТЫ"));
        assert!(synthesis.contains("РЕКОМЕНДАЦИИ"));
    }

    #[test]
    fn generate_recap_basic() {
        let chunk1 = "## Слайд 4: Инвестиции\nACTION TITLE: Рост +34%\n[CEO] Бюджет\n\n## Слайд 5: Медиа\nACTION TITLE: Digital лидирует\n".to_string();
        let chunk2 = "## Слайд 8: Продажи\nACTION TITLE: Падение -12%\n".to_string();
        let recap = generate_recap(&[chunk1, chunk2]);
        assert!(recap.contains("Чанк 1 (слайды 4-5)"));
        assert!(recap.contains("Рост +34%"));
        assert!(recap.contains("Чанк 2 (слайды 8-8)"));
        assert!(recap.contains("Падение -12%"));
    }
}
