/// Sample Rust module for parser testing.

use std::collections::HashMap;
use std::fmt;

/// A data processor that transforms records.
pub struct DataProcessor {
    config: HashMap<String, String>,
}

/// Trait for processable items.
pub trait Processable {
    fn process(&self) -> String;
}

impl DataProcessor {
    /// Create a new DataProcessor with the given config.
    pub fn new(config: HashMap<String, String>) -> Self {
        DataProcessor { config }
    }

    /// Transform a single item.
    fn transform(&self, item: &str) -> String {
        item.trim().to_lowercase()
    }
}

impl fmt::Display for DataProcessor {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "DataProcessor(keys={})", self.config.len())
    }
}

pub fn load_data(path: &str) -> Vec<String> {
    std::fs::read_to_string(path)
        .unwrap_or_default()
        .lines()
        .map(String::from)
        .collect()
}
