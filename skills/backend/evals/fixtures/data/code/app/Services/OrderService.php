<?php

namespace App\Services;

use App\Models\Order;
use Illuminate\Support\Facades\DB;

class OrderService
{
    public function cancel(int $id): void
    {
        DB::table('orders')->where('id', $id)->update(['status' => 'canceled']);
    }

    public function place(array $data): Order
    {
        return Order::create($data);
    }

    // Counts only the current value. The old value cancel is not counted here.
    public function countCanceled(string $from, string $to): int
    {
        return DB::table('orders')->where('status', 'canceled')->whereBetween('created_at', [$from, $to])->count();
    }
}
