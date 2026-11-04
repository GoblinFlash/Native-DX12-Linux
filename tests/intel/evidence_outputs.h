#ifndef NDX_TEST_EVIDENCE_OUTPUTS_H
#define NDX_TEST_EVIDENCE_OUTPUTS_H
#include "../../include/ndx_evidence.h"
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

class EvidenceOutputs {
    std::vector<std::string> paths;
    std::vector<ndx_evidence_file> files;
public:
    EvidenceOutputs() = default;
    EvidenceOutputs(const EvidenceOutputs &) = delete;
    EvidenceOutputs &operator=(const EvidenceOutputs &) = delete;
    ~EvidenceOutputs() { ndx_evidence_close(files.data(), files.size()); }
    void reserve(const std::string &prefix, const char *kind, unsigned count) {
        if (!paths.empty()) throw std::runtime_error("evidence already reserved");
        paths = {prefix + ".maps.txt", prefix + ".fdinfo.txt"};
        for (unsigned i = 0; i < count; i++)
            paths.push_back(prefix + "." + kind + std::to_string(i) + ".bin");
        for (const auto &p : paths) files.push_back({p.c_str(), nullptr});
        if (ndx_evidence_reserve(files.data(), files.size()))
            throw std::runtime_error("evidence destination collision or unavailable");
    }
    void write(unsigned slot, const void *data, size_t size) {
        if (slot >= files.size() || ndx_evidence_write(files[slot].stream, data, size))
            throw std::runtime_error("evidence write failed");
    }
    void text(unsigned slot, const std::string &s) { write(slot, s.data(), s.size()); }
    void finish() {
        if (ndx_evidence_close(files.data(), files.size()))
            throw std::runtime_error("evidence close failed");
    }
};
#endif
