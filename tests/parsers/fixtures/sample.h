// Sample C/C++ header for parser testing.

#ifndef SAMPLE_H
#define SAMPLE_H

#include <string>
#include <vector>

namespace sample {

/// Interface for data processors.
class IProcessor {
public:
    virtual ~IProcessor() = default;
    virtual std::vector<std::string> process(
        const std::vector<std::string>& data) = 0;
};

/// Utility function to load data from a file.
std::vector<std::string> loadData(const std::string& path);

}  // namespace sample

#endif  // SAMPLE_H
