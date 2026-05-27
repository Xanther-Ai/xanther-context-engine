// Sample C++ source for parser testing.

#include <string>
#include <vector>
#include <algorithm>

namespace sample {

/// Processes data records.
class DataProcessor {
public:
    DataProcessor(const std::string& config) : config_(config) {}

    std::vector<std::string> process(const std::vector<std::string>& data) {
        std::vector<std::string> result;
        result.reserve(data.size());
        for (const auto& item : data) {
            result.push_back(transform(item));
        }
        return result;
    }

private:
    std::string config_;

    std::string transform(const std::string& item) {
        std::string out = item;
        out.erase(0, out.find_first_not_of(' '));
        out.erase(out.find_last_not_of(' ') + 1);
        std::transform(out.begin(), out.end(), out.begin(), ::tolower);
        return out;
    }
};

}  // namespace sample
