<?php

namespace App\Exceptions;

use RuntimeException;

/**
 * A business rule refused an action (e.g. "stop trading before changing mode").
 * Rendered as JSON {message, code} with the given HTTP status.
 */
class DomainException extends RuntimeException
{
    public function __construct(
        string $message,
        public readonly int $status = 422,
        public readonly string $errorCode = 'refused',
    ) {
        parent::__construct($message);
    }

    public static function conflict(string $message, string $code = 'conflict'): self
    {
        return new self($message, 409, $code);
    }

    public static function forbidden(string $message, string $code = 'forbidden'): self
    {
        return new self($message, 403, $code);
    }
}
