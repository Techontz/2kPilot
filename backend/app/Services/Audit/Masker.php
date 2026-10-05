<?php

namespace App\Services\Audit;

/** Removes secrets from anything that will be logged or audited. */
class Masker
{
    public const MASK = '***';

    private const SENSITIVE = '/pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|otp|code_verifier/i';

    public static function isSensitive(string $key): bool
    {
        return (bool) preg_match(self::SENSITIVE, $key);
    }

    public static function mask(mixed $value, ?string $key = null): mixed
    {
        if ($key !== null && self::isSensitive($key)) {
            return self::MASK;
        }
        if (is_array($value)) {
            $out = [];
            foreach ($value as $k => $v) {
                $out[$k] = self::mask($v, is_string($k) ? $k : null);
            }

            return $out;
        }
        if (is_string($value)) {
            return preg_replace(
                '/(pass(?:word|wd)?|secret|token|api[_-]?key|authorization)(\s*[=:]\s*)([^\s,;&]+)/i',
                '$1$2'.self::MASK,
                $value,
            );
        }

        return $value;
    }
}
