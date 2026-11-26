// 負例: Web Animations API（element.animate）の動きに、縮小版の分岐が無い。
const title = document.querySelector('.title');

export function leave() {
  return title.animate(
    [{ transform: 'translateY(0)', opacity: 1 }, { transform: 'translateY(-120px)', opacity: 0 }],
    { duration: 1400, easing: 'ease-out', fill: 'forwards' },
  );
}
