// 負例 D1: JSX の属性で書いた動き。縮小版の分岐（useReducedMotion か prefers-reduced-motion）が無い。拡張の前は素通りした。
import { motion } from "framer-motion";

export function Panel({ label }: { label: string }) {
  return (
    <motion.div initial={{ x: 240 }} animate={{ x: 0 }} transition={{ duration: 0.9 }}>
      {label}
    </motion.div>
  );
}
