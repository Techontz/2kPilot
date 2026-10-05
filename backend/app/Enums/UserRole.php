<?php

namespace App\Enums;

enum UserRole: string
{
    case Owner = 'owner';   // full control, including trading
    case Viewer = 'viewer'; // read-only dashboards
}
