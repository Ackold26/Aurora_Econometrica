//! Structured error codes for Aurora AI Agency.
//!
//! Every user-facing error is assigned a code `[XX-NNN]` for quick diagnosis.
//! See also: `help/error-codes.html` and `5_Документация/ERROR_CODES.md`.

use std::fmt;

/// Error code categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorCode {
    // ── License ──
    LI001, // License file not found
    LI002, // Cannot read license file
    LI003, // Invalid license JSON
    LI004, // Invalid salt base64
    LI005, // License has expired
    LI006, // License bound to different machine
    LI007, // Invalid signature
    LI008, // Invalid expiry date format
    LI009, // System clock incorrect
    LI010, // License validation error

    // ── Vault ──
    VT001, // Failed to read vault file
    VT002, // Vault decryption failed (wrong key / corrupted)
    VT003, // Failed to create tar archive
    VT004, // Failed to finalize tar/gzip
    VT005, // Encrypted data too short

    // ── Claude CLI ──
    CL001, // Claude CLI not found
    CL002, // Failed to launch Claude CLI
    CL003, // Failed to capture stdout/stderr
    CL004, // Rate limit exceeded
    CL005, // Server overloaded
    CL006, // Auth error
    CL007, // Network error
    CL008, // Execution timeout

    // ── Fingerprint ──
    FP001, // WMI / hardware ID collection failed
    FP002, // COM / WMI connection error
    FP003, // Unsupported platform

    // ── Install (reserved for PS1 scripts) ──
    // IN001..IN006

    // ── System ──
    SY001, // File I/O error
    SY002, // Permission denied
    SY003, // Clock skew detected

    // ── Update ──
    UP001, // Update server error
    UP002, // Download failed
    UP003, // Checksum mismatch
    UP004, // Installation failed
    UP005, // Version parse error

    // ── Feedback ──
    FB001, // Feedback submission failed
    FB002, // Feedback rate limit exceeded

    // ── Online Auth ──
    AU001, // Server unreachable
    AU002, // License not found on server
    AU003, // License expired (server)
    AU004, // Blocked - clone detected
    AU005, // Auth cache expired, no fallback
}

impl ErrorCode {
    /// The short string like `"LI-001"`.
    pub fn code(&self) -> &'static str {
        match self {
            Self::LI001 => "LI-001",
            Self::LI002 => "LI-002",
            Self::LI003 => "LI-003",
            Self::LI004 => "LI-004",
            Self::LI005 => "LI-005",
            Self::LI006 => "LI-006",
            Self::LI007 => "LI-007",
            Self::LI008 => "LI-008",
            Self::LI009 => "LI-009",
            Self::LI010 => "LI-010",

            Self::VT001 => "VT-001",
            Self::VT002 => "VT-002",
            Self::VT003 => "VT-003",
            Self::VT004 => "VT-004",
            Self::VT005 => "VT-005",

            Self::CL001 => "CL-001",
            Self::CL002 => "CL-002",
            Self::CL003 => "CL-003",
            Self::CL004 => "CL-004",
            Self::CL005 => "CL-005",
            Self::CL006 => "CL-006",
            Self::CL007 => "CL-007",
            Self::CL008 => "CL-008",

            Self::FP001 => "FP-001",
            Self::FP002 => "FP-002",
            Self::FP003 => "FP-003",

            Self::SY001 => "SY-001",
            Self::SY002 => "SY-002",
            Self::SY003 => "SY-003",

            Self::UP001 => "UP-001",
            Self::UP002 => "UP-002",
            Self::UP003 => "UP-003",
            Self::UP004 => "UP-004",
            Self::UP005 => "UP-005",

            Self::FB001 => "FB-001",
            Self::FB002 => "FB-002",

            Self::AU001 => "AU-001",
            Self::AU002 => "AU-002",
            Self::AU003 => "AU-003",
            Self::AU004 => "AU-004",
            Self::AU005 => "AU-005",
        }
    }
}

impl fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.code())
    }
}

/// Format an error with its code: `"[LI-005] License has expired"`.
pub fn coded(code: ErrorCode, detail: &str) -> String {
    format!("[{}] {}", code.code(), detail)
}

/// Create an `anyhow::Error` with a structured error code prefix.
pub fn coded_err(code: ErrorCode, detail: &str) -> anyhow::Error {
    anyhow::anyhow!("{}", coded(code, detail))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_code_format() {
        assert_eq!(coded(ErrorCode::LI005, "License has expired"), "[LI-005] License has expired");
        assert_eq!(coded(ErrorCode::VT002, "wrong key"), "[VT-002] wrong key");
    }

    #[test]
    fn all_codes_unique() {
        use std::collections::HashSet;
        let codes = [
            ErrorCode::LI001, ErrorCode::LI002, ErrorCode::LI003, ErrorCode::LI004,
            ErrorCode::LI005, ErrorCode::LI006, ErrorCode::LI007, ErrorCode::LI008,
            ErrorCode::LI009, ErrorCode::LI010,
            ErrorCode::VT001, ErrorCode::VT002, ErrorCode::VT003, ErrorCode::VT004, ErrorCode::VT005,
            ErrorCode::CL001, ErrorCode::CL002, ErrorCode::CL003, ErrorCode::CL004,
            ErrorCode::CL005, ErrorCode::CL006, ErrorCode::CL007, ErrorCode::CL008,
            ErrorCode::FP001, ErrorCode::FP002, ErrorCode::FP003,
            ErrorCode::SY001, ErrorCode::SY002, ErrorCode::SY003,
            ErrorCode::UP001, ErrorCode::UP002, ErrorCode::UP003, ErrorCode::UP004, ErrorCode::UP005,
            ErrorCode::FB001, ErrorCode::FB002,
            ErrorCode::AU001, ErrorCode::AU002, ErrorCode::AU003, ErrorCode::AU004, ErrorCode::AU005,
        ];
        let set: HashSet<&str> = codes.iter().map(|c| c.code()).collect();
        assert_eq!(set.len(), codes.len(), "Duplicate error codes detected");
    }
}
