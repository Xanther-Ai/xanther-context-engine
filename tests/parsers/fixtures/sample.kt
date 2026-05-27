package com.example.sample

import java.util.Locale

/**
 * Sample Kotlin class for parser testing.
 */
class DataProcessor(private val config: String) {

    fun process(data: List<String>): List<String> {
        return data.map { transform(it) }
    }

    private fun transform(item: String): String {
        return item.trim().lowercase(Locale.getDefault())
    }
}

fun loadData(path: String): List<String> {
    return java.io.File(path).readLines()
}
