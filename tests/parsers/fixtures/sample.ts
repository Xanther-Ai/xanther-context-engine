/**
 * Sample TypeScript module for parser testing.
 */

import { EventEmitter } from "events";
import { readFile } from "fs/promises";

export class DataService extends EventEmitter {
    private cache: Map<string, string>;

    constructor() {
        super();
        this.cache = new Map();
    }

    async fetchData(key: string): Promise<string | null> {
        if (this.cache.has(key)) {
            return this.cache.get(key) ?? null;
        }
        const data = await readFile(key, "utf-8");
        this.cache.set(key, data);
        this.emit("fetched", key);
        return data;
    }
}

export const formatOutput = (input: string): string => {
    return input.trim().toUpperCase();
};

function parseConfig(raw: string): Record<string, string> {
    const lines = raw.split("\n");
    const result: Record<string, string> = {};
    for (const line of lines) {
        const [key, value] = line.split("=");
        if (key && value) {
            result[key.trim()] = value.trim();
        }
    }
    return result;
}
