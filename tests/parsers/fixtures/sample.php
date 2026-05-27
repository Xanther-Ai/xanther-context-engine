<?php

namespace App\Sample;

use App\Contracts\ProcessorInterface;
use App\Support\Helper;

/**
 * Sample PHP class for parser testing.
 */
class DataProcessor implements ProcessorInterface
{
    private string $config;

    public function __construct(string $config)
    {
        $this->config = $config;
    }

    public function process(array $data): array
    {
        return array_map([$this, 'transform'], $data);
    }

    private function transform(string $item): string
    {
        return strtolower(trim($item));
    }
}
