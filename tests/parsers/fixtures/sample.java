package com.example.sample;

import java.util.List;
import java.util.ArrayList;

/**
 * Sample Java class for parser testing.
 */
public class DataProcessor {
    private final String config;

    public DataProcessor(String config) {
        this.config = config;
    }

    public List<String> process(List<String> data) {
        List<String> result = new ArrayList<>();
        for (String item : data) {
            result.add(transform(item));
        }
        return result;
    }

    private String transform(String item) {
        return item.trim().toLowerCase();
    }
}
