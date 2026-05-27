# Sample Ruby module for parser testing.

require "json"
require_relative "helpers"

module Sample
  # Processes data records.
  class DataProcessor
    attr_reader :config

    def initialize(config)
      @config = config
    end

    def process(data)
      data.map { |item| transform(item) }
    end

    private

    def transform(item)
      item.strip.downcase
    end
  end
end
