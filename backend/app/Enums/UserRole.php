<?php

namespace App\Enums;

enum UserRole: string
{
    case User = 'user';   // trades their own accounts; sees only their own records
    case Admin = 'admin'; // a user who also operates the platform (halt, Horizon, all records read-only)
}
