// Package sample provides example types for parser testing.
package sample

import (
	"fmt"
	"strings"
)

// DataProcessor handles data transformation.
type DataProcessor struct {
	Config map[string]string
}

// NewDataProcessor creates a new DataProcessor instance.
func NewDataProcessor(config map[string]string) *DataProcessor {
	return &DataProcessor{Config: config}
}

// Process transforms a slice of strings.
func (dp *DataProcessor) Process(data []string) []string {
	result := make([]string, 0, len(data))
	for _, item := range data {
		result = append(result, dp.transform(item))
	}
	return result
}

func (dp *DataProcessor) transform(item string) string {
	return strings.TrimSpace(fmt.Sprintf("%s_processed", item))
}
