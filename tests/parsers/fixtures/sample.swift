/// Sample Swift module for parser testing.

import Foundation

/// Protocol for processable items.
protocol Processable {
    func process(data: [String]) -> [String]
}

/// Processes data records.
class DataProcessor: Processable {
    let config: String

    init(config: String) {
        self.config = config
    }

    func process(data: [String]) -> [String] {
        return data.map { transform(item: $0) }
    }

    private func transform(item: String) -> String {
        return item.trimmingCharacters(in: .whitespaces).lowercased()
    }
}

func loadData(from path: String) -> [String] {
    let content = try? String(contentsOfFile: path)
    return content?.components(separatedBy: "\n") ?? []
}
