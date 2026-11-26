// 負例: 音を鳴らすのに、同じモジュールに消音の手段が無い。別の CSS の色のトークン --muted を、消音と取り違えない。
const chime = new Audio('chime.mp3');

document.querySelector('.start').addEventListener('click', () => {
  chime.play();
});
