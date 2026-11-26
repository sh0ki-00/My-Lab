<?php

namespace App\Models;

class Order extends Model
{
    protected $table = 'orders';

    // Order status values written by the application.
    public const STATUSES = ['paid', 'shipped', 'canceled'];

    // Soft delete is recorded in is_deleted. deleted_at is never written.
    public const SOFT_DELETE_COLUMN = 'is_deleted';
}
