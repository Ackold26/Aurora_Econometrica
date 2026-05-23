use anyhow::{Context, Result};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Stdio;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

// ── Dependency checking & auto-install ─────────────────────

/// Status of PPTX pipeline dependencies.
#[derive(Debug, Clone, Serialize)]
pub struct DependencyStatus {
    pub python_available: bool,
    pub python_version: String,
    pub missing_packages: Vec<String>,
    pub all_ok: bool,
}

/// Required pip packages for PPTX pipeline.
const REQUIRED_PACKAGES: &[&str] = &["pptx", "docx"];
/// Package names for pip install (different from import names).
const PIP_PACKAGES: &[&str] = &["python-pptx", "python-docx"];

/// Check if Python and required packages are available.
pub fn check_dependencies() -> DependencyStatus {
    let python = if cfg!(windows) { "python" } else { "python3" };

    // Check Python
    let py_result = std::process::Command::new(python)
        .args(["--version"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();

    let (python_available, python_version) = match py_result {
        Ok(output) if output.status.success() => {
            let ver = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let ver = if ver.is_empty() {
                String::from_utf8_lossy(&output.stderr).trim().to_string()
            } else {
                ver
            };
            (true, ver)
        }
        _ => (false, String::new()),
    };

    if !python_available {
        return DependencyStatus {
            python_available: false,
            python_version: String::new(),
            missing_packages: PIP_PACKAGES.iter().map(|s| s.to_string()).collect(),
            all_ok: false,
        };
    }

    // Check each required package via importlib
    let mut missing = Vec::new();
    for (import_name, pip_name) in REQUIRED_PACKAGES.iter().zip(PIP_PACKAGES.iter()) {
        let check = std::process::Command::new(python)
            .args(["-c", &format!("import {import_name}")])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .output();

        match check {
            Ok(output) if output.status.success() => {}
            _ => missing.push(pip_name.to_string()),
        }
    }

    let all_ok = missing.is_empty();
    DependencyStatus { python_available, python_version, missing_packages: missing, all_ok }
}

/// Install missing pip packages. Returns Ok(installed_count) or Err.
pub fn install_packages(packages: &[String]) -> Result<usize> {
    if packages.is_empty() {
        return Ok(0);
    }
    let python = if cfg!(windows) { "python" } else { "python3" };
    let mut args = vec!["-m", "pip", "install", "--user", "--quiet"];
    let pkg_refs: Vec<&str> = packages.iter().map(|s| s.as_str()).collect();
    args.extend(&pkg_refs);

    info!("Installing pip packages: {:?}", packages);

    let output = std::process::Command::new(python)
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .context("Failed to run pip install")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("pip install failed: {}", stderr.chars().take(500).collect::<String>());
    }

    info!("Successfully installed {} packages", packages.len());
    Ok(packages.len())
}

/// Find the pptx_pipeline executable or script.
/// Priority: bundled .exe → bundled .py (resources) → dev script
fn find_pipeline() -> Result<(String, Vec<String>)> {
    // 1. Bundled exe next to the app binary (future: PyInstaller build)
    if let Ok(exe) = std::env::current_exe() {
        let dir = exe.parent().unwrap_or(Path::new("."));
        let pipeline_exe = dir.join("pptx_pipeline.exe");
        if pipeline_exe.exists() {
            return Ok((pipeline_exe.to_string_lossy().to_string(), vec![]));
        }

        // 2. Bundled .py script in resources
        for subdir in &["sidecar", "_up_/sidecar"] {
            let bundled_script = dir.join(subdir).join("pptx_pipeline.py");
            if bundled_script.exists() {
                let python = if cfg!(windows) { "python" } else { "python3" };
                return Ok((python.to_string(), vec![bundled_script.to_string_lossy().to_string()]));
            }
        }
    }

    // 3. Dev: use CARGO_MANIFEST_DIR + sidecar/
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR")
        .unwrap_or_else(|_| ".".to_string());
    let script = PathBuf::from(&manifest_dir)
        .join("sidecar")
        .join("pptx_pipeline.py");

    if script.exists() {
        let python = if cfg!(windows) { "python" } else { "python3" };
        Ok((python.to_string(), vec![script.to_string_lossy().to_string()]))
    } else {
        anyhow::bail!("pptx_pipeline not found (checked bundled exe, bundled py, and dev script)")
    }
}

/// Pipeline timeout - kill process if it takes longer than this.
const PIPELINE_TIMEOUT_SECS: u64 = 60;

/// Run the pipeline with given mode and args. Returns stdout as String.
/// Kills the subprocess if it exceeds PIPELINE_TIMEOUT_SECS.
fn run_pipeline(mode: &str, args: &[&str]) -> Result<String> {
    let (cmd, mut prefix_args) = find_pipeline()?;
    prefix_args.push(mode.to_string());
    prefix_args.extend(args.iter().map(|a| a.to_string()));

    debug!("pptx_pipeline: {} {:?}", cmd, prefix_args);

    // Launch Python directly (NOT via cmd /C) to avoid cp1251 encoding on Russian Windows.
    // PYTHONIOENCODING=utf-8 forces UTF-8 for stdin/stdout/stderr.
    // PYTHONUTF8=1 enables UTF-8 mode globally (Python 3.7+).
    #[cfg(windows)]
    let child = {
        std::process::Command::new(&cmd)
            .args(&prefix_args)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
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
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .context("Failed to spawn pptx_pipeline")?
    };

    // Wait with timeout - prevent hanging process from blocking the app
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

/// Add summary slides to PPTX from synthesis markdown sections.
pub fn inject_summary_slides(
    pptx_path: &Path,
    synthesis_md: &Path,
    styles_json: &Path,
    slides_json: &Path,
    output_path: &Path,
) -> Result<()> {
    info!("PPTX inject summary slides: {} → {}", pptx_path.display(), output_path.display());

    let result = run_pipeline("inject-summary-slides", &[
        &pptx_path.to_string_lossy(),
        &synthesis_md.to_string_lossy(),
        &styles_json.to_string_lossy(),
        &slides_json.to_string_lossy(),
        &output_path.to_string_lossy(),
    ])?;

    if let Ok(json) = serde_json::from_str::<serde_json::Value>(&result) {
        let added = json["slides_added"].as_u64().unwrap_or(0);
        let status = json["status"].as_str().unwrap_or("?");
        info!("inject_summary_slides: status={status}, slides_added={added}");
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

    // Lift OnceLock-cached slide-header regex outside loop — clippy
    // (regex_creation_in_loops) не recognize OnceLock pattern intra-block.
    use std::sync::OnceLock;
    static SLIDE_HEADER_RE: OnceLock<regex::Regex> = OnceLock::new();
    let slide_header_re = SLIDE_HEADER_RE.get_or_init(|| {
        regex::Regex::new(r"(?i)^#{2,3}\s*(?:(?:slide|слайд)\s*№?\s*\d+|\d+\.\s)").unwrap()
    });

    for line in response.lines() {
        let trimmed = line.trim();

        // Check if this line starts a synthesis section
        let is_synthesis_header = synthesis_prefixes.iter().any(|p| {
            trimmed.to_uppercase().starts_with(&p.to_uppercase())
        });

        // Check if this line starts a slide section
        let is_slide_header = slide_header_re.is_match(trimmed);

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
        let title = slide["title"].as_str().unwrap_or("-");
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
    selected_slides: Option<&[u32]>,
) -> Result<ChunkSplit> {
    let data_slides: Vec<&serde_json::Value> = slides
        .iter()
        .filter(|s| s["type"] == "data")
        .filter(|s| {
            match selected_slides {
                Some(nums) => {
                    s["slide_num"].as_u64()
                        .map(|n| nums.contains(&(n as u32)))
                        .unwrap_or(false)
                }
                None => true,
            }
        })
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
        use std::collections::hash_map::Entry;
        for note in notes {
            if let Some(num) = note["slide_num"].as_u64() {
                match all_notes.entry(num as u32) {
                    Entry::Vacant(e) => { e.insert(note); }
                    Entry::Occupied(mut e) => {
                        let existing_len = e.get()["text"].as_str().map_or(0, |s| s.len());
                        let new_len = note["text"].as_str().map_or(0, |s| s.len());
                        if new_len > existing_len {
                            debug!("merge_chunk_notes: slide {} overwritten ({}→{} chars)", num, existing_len, new_len);
                            e.insert(note);
                        }
                    }
                }
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

        // Extract slide headline as key findings (supports both "ЗАГОЛОВОК:" and legacy "ACTION TITLE:")
        let mut titles: Vec<String> = Vec::new();
        for note in &notes {
            if let Some(text) = note["text"].as_str() {
                for line in text.lines() {
                    let title_opt = if line.starts_with("ЗАГОЛОВОК:") {
                        Some(line.trim_start_matches("ЗАГОЛОВОК:").trim())
                    } else if line.starts_with("ACTION TITLE:") {
                        Some(line.trim_start_matches("ACTION TITLE:").trim())
                    } else {
                        None
                    };
                    if let Some(title) = title_opt {
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

// ─── Aurora Index: precompute analytics ──────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricPoint {
    pub name: String,
    pub values: Vec<Option<f64>>,
    pub categories: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrendInfo {
    pub metric_name: String,
    pub direction: String, // "up" | "down" | "flat"
    pub change_pct: f64,
    pub slope: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnomalyInfo {
    pub slide_num: u32,
    pub metric_name: String,
    pub category: String,
    pub value: f64,
    pub expected: f64,
    pub deviation_pct: f64,
    pub severity: String, // "high" (>30%) | "medium" (>15%)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CrossSlideLink {
    pub from_slide: u32,
    pub to_slide: u32,
    pub link_type: String, // "same_metric" | "inverse" | "causal_candidate"
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThematicBlock {
    pub name: String,
    pub slides: Vec<u32>,
    pub health: String, // "good" | "warning" | "critical"
    pub anomaly_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthSummary {
    pub data_coverage: f64,
    pub anomaly_count: usize,
    pub high_severity_count: usize,
    pub block_count: usize,
    pub cross_link_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PresentationAnalytics {
    pub blocks: Vec<ThematicBlock>,
    pub anomalies: Vec<AnomalyInfo>,
    pub trends: Vec<TrendInfo>,
    pub cross_links: Vec<CrossSlideLink>,
    pub health: HealthSummary,
}

pub fn compute_analytics(slides: &[serde_json::Value]) -> PresentationAnalytics {
    let data_slides: Vec<&serde_json::Value> = slides
        .iter()
        .filter(|s| s["type"] == "data")
        .collect();

    // 1. Extract numeric series from all charts
    let mut all_series: Vec<(u32, MetricPoint)> = Vec::new();
    for slide in &data_slides {
        let slide_num = slide["slide_num"].as_u64().unwrap_or(0) as u32;
        if let Some(charts) = slide["charts"].as_array() {
            for chart in charts {
                if let Some(series) = chart["series"].as_array() {
                    let categories: Vec<String> = chart["categories"]
                        .as_array()
                        .map(|a| {
                            a.iter()
                                .filter_map(|v| v.as_str().map(String::from))
                                .collect()
                        })
                        .unwrap_or_default();
                    for s in series {
                        let name = s["name"].as_str().unwrap_or("").to_string();
                        let values: Vec<Option<f64>> = s["values"]
                            .as_array()
                            .map(|a| a.iter().map(|v| v.as_f64()).collect())
                            .unwrap_or_default();
                        if !values.is_empty() && !name.is_empty() {
                            all_series.push((
                                slide_num,
                                MetricPoint {
                                    name,
                                    values,
                                    categories: categories.clone(),
                                },
                            ));
                        }
                    }
                }
            }
        }
    }

    let trends = compute_trends(&all_series);
    let anomalies = detect_anomalies(&all_series);
    let blocks = group_thematic_blocks(&data_slides, &anomalies);
    let cross_links = find_cross_slide_links(&all_series);

    let health = HealthSummary {
        data_coverage: data_slides.len() as f64 / slides.len().max(1) as f64,
        anomaly_count: anomalies.len(),
        high_severity_count: anomalies.iter().filter(|a| a.severity == "high").count(),
        block_count: blocks.len(),
        cross_link_count: cross_links.len(),
    };

    PresentationAnalytics {
        blocks,
        anomalies,
        trends,
        cross_links,
        health,
    }
}

fn compute_trends(all_series: &[(u32, MetricPoint)]) -> Vec<TrendInfo> {
    let mut trends = Vec::new();
    for (_slide_num, metric) in all_series {
        let valid: Vec<(f64, f64)> = metric
            .values
            .iter()
            .enumerate()
            .filter_map(|(i, v)| v.map(|val| (i as f64, val)))
            .collect();
        if valid.len() < 3 {
            continue;
        }

        let n = valid.len() as f64;
        let sum_x: f64 = valid.iter().map(|(x, _)| x).sum();
        let sum_y: f64 = valid.iter().map(|(_, y)| y).sum();
        let sum_xy: f64 = valid.iter().map(|(x, y)| x * y).sum();
        let sum_x2: f64 = valid.iter().map(|(x, _)| x * x).sum();

        let denom = n * sum_x2 - sum_x * sum_x;
        if denom.abs() < 1e-10 {
            continue;
        }

        let slope = (n * sum_xy - sum_x * sum_y) / denom;
        let mean_y = sum_y / n;
        let normalized_slope = if mean_y.abs() > 1e-10 {
            slope / mean_y
        } else {
            0.0
        };

        let first_val = valid.first().map(|(_, y)| *y).unwrap_or(0.0);
        let last_val = valid.last().map(|(_, y)| *y).unwrap_or(0.0);
        let change_pct = if first_val.abs() > 1e-10 {
            (last_val - first_val) / first_val * 100.0
        } else {
            0.0
        };

        let direction = if normalized_slope > 0.01 {
            "up"
        } else if normalized_slope < -0.01 {
            "down"
        } else {
            "flat"
        };

        trends.push(TrendInfo {
            metric_name: metric.name.clone(),
            direction: direction.to_string(),
            change_pct,
            slope: normalized_slope,
        });
    }
    trends
}

fn detect_anomalies(all_series: &[(u32, MetricPoint)]) -> Vec<AnomalyInfo> {
    let mut anomalies = Vec::new();
    for (slide_num, metric) in all_series {
        let valid: Vec<(usize, f64)> = metric
            .values
            .iter()
            .enumerate()
            .filter_map(|(i, v)| v.map(|val| (i, val)))
            .collect();
        if valid.len() < 3 {
            continue;
        }

        let n = valid.len() as f64;
        let sum_x: f64 = valid.iter().map(|(x, _)| *x as f64).sum();
        let sum_y: f64 = valid.iter().map(|(_, y)| y).sum();
        let sum_xy: f64 = valid.iter().map(|(x, y)| *x as f64 * y).sum();
        let sum_x2: f64 = valid.iter().map(|(x, _)| (*x as f64) * (*x as f64)).sum();

        let denom = n * sum_x2 - sum_x * sum_x;
        if denom.abs() < 1e-10 {
            continue;
        }

        let slope = (n * sum_xy - sum_x * sum_y) / denom;
        let intercept = (sum_y - slope * sum_x) / n;

        for (i, val) in &valid {
            let expected = intercept + slope * (*i as f64);
            if expected.abs() < 1e-10 {
                continue;
            }
            let deviation_pct = ((val - expected) / expected * 100.0).abs();

            if deviation_pct > 15.0 {
                let category = metric
                    .categories
                    .get(*i)
                    .cloned()
                    .unwrap_or_else(|| format!("point {}", i));
                let severity = if deviation_pct > 30.0 { "high" } else { "medium" };
                anomalies.push(AnomalyInfo {
                    slide_num: *slide_num,
                    metric_name: metric.name.clone(),
                    category,
                    value: *val,
                    expected,
                    deviation_pct,
                    severity: severity.to_string(),
                });
            }
        }
    }
    anomalies.sort_by(|a, b| {
        b.severity
            .cmp(&a.severity)
            .then(b.deviation_pct.partial_cmp(&a.deviation_pct).unwrap_or(std::cmp::Ordering::Equal))
    });
    anomalies.truncate(15);
    anomalies
}

fn group_thematic_blocks(
    data_slides: &[&serde_json::Value],
    anomalies: &[AnomalyInfo],
) -> Vec<ThematicBlock> {
    let keyword_map: &[(&[&str], &str)] = &[
        (
            &["инвестиц", "бюджет", "spend", "затрат"],
            "Инвестиции",
        ),
        (
            &["медиа", "канал", "mix", "микс", "split"],
            "Медиамикс",
        ),
        (
            &["конкурент", "sov", "share of voice", "доля"],
            "Конкуренты",
        ),
        (
            &["потребит", "brand pulse", "знание", "aware", "лояльн"],
            "Потребитель",
        ),
        (
            &["digital", "диджитал", "cpm", "ctr", "cpc", "онлайн"],
            "Digital",
        ),
        (&["продаж", "sales", "выручк", "revenue"], "Продажи"),
        (
            &["grp", "trp", "рейтинг", "охват", "reach", "частот"],
            "Медиадавление",
        ),
    ];

    let mut blocks: Vec<ThematicBlock> = Vec::new();

    for slide in data_slides {
        let slide_num = slide["slide_num"].as_u64().unwrap_or(0) as u32;
        let title = slide["title"].as_str().unwrap_or("").to_lowercase();

        let block_name = keyword_map
            .iter()
            .find(|(keywords, _)| keywords.iter().any(|kw| title.contains(kw)))
            .map(|(_, name)| name.to_string())
            .unwrap_or_else(|| "Другое".to_string());

        let anomaly_count = anomalies.iter().filter(|a| a.slide_num == slide_num).count();

        if let Some(last) = blocks.last_mut() {
            if last.name == block_name {
                last.slides.push(slide_num);
                last.anomaly_count += anomaly_count;
                continue;
            }
        }
        blocks.push(ThematicBlock {
            name: block_name,
            slides: vec![slide_num],
            health: "good".to_string(),
            anomaly_count,
        });
    }

    for block in &mut blocks {
        let high = anomalies
            .iter()
            .filter(|a| block.slides.contains(&a.slide_num) && a.severity == "high")
            .count();
        block.health = if high > 0 {
            "critical".to_string()
        } else if block.anomaly_count > 0 {
            "warning".to_string()
        } else {
            "good".to_string()
        };
    }

    blocks
}

fn find_cross_slide_links(all_series: &[(u32, MetricPoint)]) -> Vec<CrossSlideLink> {
    let mut links = Vec::new();

    for (i, (slide_a, metric_a)) in all_series.iter().enumerate() {
        for (slide_b, metric_b) in all_series.iter().skip(i + 1) {
            if slide_a == slide_b {
                continue;
            }

            let name_a = metric_a.name.to_lowercase();
            let name_a = name_a.trim();
            let name_b = metric_b.name.to_lowercase();
            let name_b = name_b.trim();

            if name_a.len() < 4 || name_b.len() < 4 {
                continue;
            }

            if name_a == name_b || name_a.contains(name_b) || name_b.contains(name_a) {
                let dir_a = trend_direction(&metric_a.values);
                let dir_b = trend_direction(&metric_b.values);

                let link_type = if (dir_a == "up" && dir_b == "down")
                    || (dir_a == "down" && dir_b == "up")
                {
                    "inverse"
                } else {
                    "same_metric"
                };

                links.push(CrossSlideLink {
                    from_slide: *slide_a,
                    to_slide: *slide_b,
                    link_type: link_type.to_string(),
                    description: format!(
                        "\"{}\" на слайдах {} и {}",
                        metric_a.name, slide_a, slide_b
                    ),
                });
            }
        }
    }

    links.truncate(10);
    links
}

fn trend_direction(values: &[Option<f64>]) -> &'static str {
    let valid: Vec<f64> = values.iter().filter_map(|v| *v).collect();
    if valid.len() < 2 {
        return "flat";
    }
    let first = valid[0];
    let last = valid[valid.len() - 1];
    if first.abs() < 1e-10 || last.abs() < 1e-10 {
        return "flat";
    }
    let change = (last - first) / first;
    if change > 0.05 {
        "up"
    } else if change < -0.05 {
        "down"
    } else {
        "flat"
    }
}

pub fn format_analytics_context(analytics: &PresentationAnalytics) -> String {
    let mut out = String::with_capacity(2048);
    out.push_str("[AURORA INDEX - ВСПОМОГАТЕЛЬНЫЕ ДАННЫЕ (НЕ основное задание)]\n\
        Ниже - автоматический предварительный анализ числовых данных из графиков. \
        Используй как ДОПОЛНИТЕЛЬНЫЙ контекст при выполнении ОСНОВНОГО задания. \
        НЕ меняй формат ответа - выполняй задание из команды.\n\n");
    out.push_str(&format!(
        "{} блоков, {} аномалий ({} критических), {} межслайдовых связей\n\n",
        analytics.health.block_count,
        analytics.health.anomaly_count,
        analytics.health.high_severity_count,
        analytics.health.cross_link_count,
    ));

    if !analytics.blocks.is_empty() {
        out.push_str("БЛОКИ:\n");
        for b in &analytics.blocks {
            let slides_str = if b.slides.len() > 2 {
                format!(
                    "{}-{}",
                    b.slides.first().unwrap(),
                    b.slides.last().unwrap()
                )
            } else {
                b.slides
                    .iter()
                    .map(|n| n.to_string())
                    .collect::<Vec<_>>()
                    .join(", ")
            };
            let health_icon = match b.health.as_str() {
                "critical" => "🔴",
                "warning" => "🟡",
                _ => "🟢",
            };
            out.push_str(&format!(
                "- {} {} (сл. {}) [{}]\n",
                health_icon,
                b.name,
                slides_str,
                if b.anomaly_count > 0 {
                    format!("{} аном.", b.anomaly_count)
                } else {
                    "ок".to_string()
                }
            ));
        }
        out.push('\n');
    }

    if !analytics.anomalies.is_empty() {
        out.push_str("АНОМАЛИИ:\n");
        for a in analytics.anomalies.iter().take(10) {
            out.push_str(&format!(
                "- Сл.{} «{}» {}: {:.0} (ожид. {:.0}, откл. {:.0}%) [{}]\n",
                a.slide_num,
                a.metric_name,
                a.category,
                a.value,
                a.expected,
                a.deviation_pct,
                a.severity
            ));
        }
        out.push('\n');
    }

    if !analytics.trends.is_empty() {
        out.push_str("ТРЕНДЫ:\n");
        for t in analytics.trends.iter().take(10) {
            let arrow = match t.direction.as_str() {
                "up" => "↑",
                "down" => "↓",
                _ => "→",
            };
            out.push_str(&format!("- «{}» {} {:.0}%\n", t.metric_name, arrow, t.change_pct));
        }
        out.push('\n');
    }

    if !analytics.cross_links.is_empty() {
        out.push_str("СВЯЗИ:\n");
        for l in analytics.cross_links.iter().take(8) {
            out.push_str(&format!(
                "- Сл.{} → Сл.{}: {} [{}]\n",
                l.from_slide, l.to_slide, l.description, l.link_type
            ));
        }
        out.push('\n');
    }

    out.push_str(
        "Эти данные - вспомогательные. Выполняй ОСНОВНОЕ задание из команды (послайдовые комментарии, check, executive summary и т.п.). Упоминай аномалии и тренды в комментариях где релевантно.\n",
    );
    out
}

#[cfg(test)]
mod analytics_tests {
    use super::*;

    fn make_slide(num: u32, title: &str, series: Vec<(&str, Vec<f64>)>) -> serde_json::Value {
        let chart_series: Vec<serde_json::Value> = series
            .iter()
            .map(|(name, vals)| {
                serde_json::json!({"name": name, "values": vals})
            })
            .collect();
        serde_json::json!({
            "slide_num": num, "type": "data", "title": title,
            "charts": [{"chart_type": "LINE", "series": chart_series, "categories": ["Q1","Q2","Q3","Q4"]}],
            "texts": [], "tables": []
        })
    }

    #[test]
    fn test_trend_up() {
        let slides = vec![make_slide(
            1,
            "Продажи",
            vec![("Revenue", vec![100.0, 120.0, 140.0, 160.0])],
        )];
        let a = compute_analytics(&slides);
        assert_eq!(a.trends.len(), 1);
        assert_eq!(a.trends[0].direction, "up");
        assert!(a.trends[0].change_pct > 50.0);
    }

    #[test]
    fn test_anomaly_detected() {
        let slides = vec![make_slide(
            1,
            "Бюджет",
            vec![("TV", vec![100.0, 105.0, 200.0, 110.0])],
        )];
        let a = compute_analytics(&slides);
        assert!(!a.anomalies.is_empty());
        assert!(a.anomalies.iter().any(|a| a.value > 150.0));
    }

    #[test]
    fn test_thematic_grouping() {
        let slides = vec![
            make_slide(
                1,
                "Инвестиции в рекламу",
                vec![("Budget", vec![10.0, 20.0, 30.0])],
            ),
            make_slide(
                2,
                "Инвестиции по каналам",
                vec![("TV", vec![5.0, 10.0, 15.0])],
            ),
            make_slide(3, "Конкуренты SOV", vec![("SOV", vec![30.0, 28.0, 25.0])]),
        ];
        let a = compute_analytics(&slides);
        assert!(a
            .blocks
            .iter()
            .any(|b| b.name == "Инвестиции" && b.slides.len() == 2));
        assert!(a.blocks.iter().any(|b| b.name == "Конкуренты"));
    }

    #[test]
    fn test_cross_slide_link() {
        let slides = vec![
            make_slide(
                1,
                "Digital spend",
                vec![("Digital", vec![100.0, 150.0, 200.0])],
            ),
            make_slide(
                5,
                "Digital ROI",
                vec![("Digital", vec![1.2, 1.5, 1.8])],
            ),
        ];
        let a = compute_analytics(&slides);
        assert!(!a.cross_links.is_empty());
    }

    #[test]
    fn test_empty_slides() {
        let slides = vec![serde_json::json!({
            "slide_num": 1, "type": "title", "title": "Cover",
            "charts": [], "texts": [], "tables": []
        })];
        let a = compute_analytics(&slides);
        assert!(a.trends.is_empty());
        assert!(a.anomalies.is_empty());
    }

    #[test]
    fn test_format_context() {
        let slides = vec![make_slide(
            1,
            "Продажи",
            vec![("Revenue", vec![100.0, 120.0, 140.0, 160.0])],
        )];
        let a = compute_analytics(&slides);
        let ctx = format_analytics_context(&a);
        assert!(ctx.contains("AURORA INDEX"));
        assert!(ctx.contains("ТРЕНДЫ"));
    }
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
        let result = split_into_chunks(&slides, tmp.path(), 500, None).unwrap();
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
        let result = split_into_chunks(&slides, tmp.path(), 1_000_000, None).unwrap();
        assert_eq!(result.chunk_count, 1);
    }

    #[test]
    fn merge_chunk_notes_dedup() {
        // chunk2 has a longer version of slide 5 → should win
        let chunk1 = "## Слайд 4: A\nACTION TITLE: X\n[CEO] ...\n\n## Слайд 5: B\nACTION TITLE: Y\n[CEO] short\n".to_string();
        let chunk2 = "## Слайд 6: C\nACTION TITLE: Z\n\n## Слайд 5: B updated\nACTION TITLE: Y2\n[CEO] longer version with more detail here\n".to_string();
        let notes = merge_chunk_notes(&[chunk1, chunk2]);
        assert_eq!(notes.len(), 3); // slides 4, 5, 6
        // Slide 5 from chunk2 wins (longer content)
        let slide5 = notes.iter().find(|n| n["slide_num"] == 5).unwrap();
        assert!(slide5["text"].as_str().unwrap().contains("Y2"));
    }

    #[test]
    fn merge_chunk_notes_keeps_longer() {
        // chunk2 has a shorter version of slide 5 → chunk1 version should be preserved
        let chunk1 = "## Слайд 5: B\nACTION TITLE: Y\n[CEO] long detailed analysis here with benchmark and recommendation\n".to_string();
        let chunk2 = "## Слайд 5: B retry\nACTION TITLE: Y short\n".to_string();
        let notes = merge_chunk_notes(&[chunk1, chunk2]);
        assert_eq!(notes.len(), 1);
        // Slide 5 from chunk1 preserved (longer content)
        let slide5 = notes.iter().find(|n| n["slide_num"] == 5).unwrap();
        assert!(slide5["text"].as_str().unwrap().contains("benchmark"));
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

## БЛОК: Инвестиции - слайды 4-5
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
