<?php

namespace App\Services\Engine;

use RuntimeException;

/**
 * The trading engine answered with an error (or could not be reached).
 * The message is written for the dashboard user; it never contains secrets.
 */
class EngineException extends RuntimeException
{
    public function __construct(
        string $message,
        public readonly int $status = 502,
        public readonly string $errorCode = 'engine_error',
        public readonly array $details = [], // structured detail, e.g. ['problems' => [...]]
    ) {
        parent::__construct($message);
    }

    /** The status Laravel answers with: validation/conflict errors pass through, the rest is 502/503. */
    public function httpStatus(): int
    {
        return match (true) {
            in_array($this->status, [403, 404, 409, 422], true) => $this->status,
            $this->status === 503 => 503,
            default => 502,
        };
    }

    /** Plain-English problems the engine listed (e.g. why a rule set is invalid). */
    public function problems(): array
    {
        return array_values(array_filter((array) ($this->details['problems'] ?? []), 'is_string'));
    }

    public static function unreachable(): self
    {
        return new self(
            'The trading engine is not reachable right now. Please try again in a moment.',
            503,
            'engine_unreachable',
        );
    }
}
