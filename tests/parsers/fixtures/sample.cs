using System;
using System.Collections.Generic;

namespace Sample
{
    /// <summary>
    /// Sample C# class for parser testing.
    /// </summary>
    public class DataProcessor
    {
        private readonly string _config;

        public DataProcessor(string config)
        {
            _config = config;
        }

        public List<string> Process(List<string> data)
        {
            var result = new List<string>();
            foreach (var item in data)
            {
                result.Add(Transform(item));
            }
            return result;
        }

        private string Transform(string item)
        {
            return item.Trim().ToLower();
        }
    }
}
