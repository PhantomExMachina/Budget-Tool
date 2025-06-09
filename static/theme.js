const themes = {
  cyborg: { mode: 'dark', font: "'Orbitron', sans-serif", url: 'https://fonts.googleapis.com/css2?family=Orbitron&display=swap' },
  darkly: { mode: 'dark', font: "'Share Tech Mono', monospace", url: 'https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap' },
  flatly: { mode: 'light', font: "'Open Sans', sans-serif", url: 'https://fonts.googleapis.com/css2?family=Open+Sans&display=swap' },
  litera: { mode: 'light', font: "'Lora', serif", url: 'https://fonts.googleapis.com/css2?family=Lora&display=swap' },
  solar: { mode: 'light', font: "'Inconsolata', monospace", url: 'https://fonts.googleapis.com/css2?family=Inconsolata&display=swap' }
};
const bootBase = 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.1/dist/';
const customLink = document.getElementById('custom-theme-link');
const staticBase = customLink.href.replace(/style-(?:dark|light)\.css$/, '');
const themeSelect = document.getElementById('theme-select');
function applyTheme(name) {
  if (!themes[name]) name = 'cyborg';
  document.getElementById('theme-link').href = `${bootBase}${name}/bootstrap.min.css`;
  const styleFile = themes[name].mode === 'dark' ? 'style-dark.css' : 'style-light.css';
  customLink.href = `${staticBase}${styleFile}`;
  document.getElementById('font-link').href = themes[name].url;
  document.documentElement.style.setProperty('--app-font', themes[name].font);
  localStorage.setItem('theme', name);
  themeSelect.value = name;
}
themeSelect.addEventListener('change', () => applyTheme(themeSelect.value));
document.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('theme') || 'cyborg';
  applyTheme(saved);
});
