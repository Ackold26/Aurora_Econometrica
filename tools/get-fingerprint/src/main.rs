use sha2::{Digest, Sha256};
use serde::Deserialize;
use wmi::{COMLibrary, WMIConnection};

fn main() {
    let com = COMLibrary::new().expect("COM init failed");
    let wmi_con = WMIConnection::new(com).expect("WMI connect failed");

    let mut ids = Vec::new();

    #[derive(Deserialize)]
    #[serde(rename_all = "PascalCase")]
    struct CsProduct {
        #[serde(rename = "UUID")]
        uuid: String,
    }

    if let Ok(results) = wmi_con.raw_query::<CsProduct>("SELECT UUID FROM Win32_ComputerSystemProduct") {
        if let Some(item) = results.first() {
            let uuid = item.uuid.trim();
            if !uuid.is_empty() {
                ids.push(format!("machine-uuid:{uuid}"));
            }
        }
    }

    #[derive(Deserialize)]
    #[serde(rename_all = "PascalCase")]
    struct DiskDrive {
        serial_number: Option<String>,
    }

    if let Ok(results) = wmi_con.raw_query::<DiskDrive>("SELECT SerialNumber FROM Win32_DiskDrive") {
        if let Some(item) = results.first() {
            if let Some(ref serial) = item.serial_number {
                let serial = serial.trim();
                if !serial.is_empty() {
                    ids.push(format!("disk-serial:{serial}"));
                }
            }
        }
    }

    #[derive(Deserialize)]
    #[serde(rename_all = "PascalCase")]
    struct BaseBoard {
        serial_number: Option<String>,
    }

    if let Ok(results) = wmi_con.raw_query::<BaseBoard>("SELECT SerialNumber FROM Win32_BaseBoard") {
        if let Some(item) = results.first() {
            if let Some(ref serial) = item.serial_number {
                let serial = serial.trim();
                if !serial.is_empty() {
                    ids.push(format!("board-serial:{serial}"));
                }
            }
        }
    }

    let mut hasher = Sha256::new();
    for component in &ids {
        hasher.update(component.as_bytes());
        hasher.update(b"|");
    }
    let hash = hasher.finalize();
    let fingerprint = hex::encode(hash);
    println!("{fingerprint}");
}
