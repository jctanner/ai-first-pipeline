function switchStratTab(name) {
  document.querySelectorAll('#strat-tab-nav ~ .tab-panel').forEach(function(p) {
    p.classList.remove('active');
  });
  document.querySelectorAll('.strat-tab-btn').forEach(function(b) {
    b.classList.remove('active', 'text-gray-900', 'dark:text-white', 'border-primary-600');
    b.classList.add('text-gray-500', 'dark:text-gray-400', 'border-transparent');
  });
  document.getElementById('strat-tab-' + name).classList.add('active');
  document.querySelectorAll('.strat-tab-btn').forEach(function(b) {
    if (b.getAttribute('onclick') === "switchStratTab('" + name + "')") {
      b.classList.add('active', 'text-gray-900', 'dark:text-white', 'border-primary-600');
      b.classList.remove('text-gray-500', 'dark:text-gray-400', 'border-transparent');
    }
  });
  var panel = document.getElementById('strat-tab-' + name);
  if (typeof marked !== 'undefined') {
    panel.querySelectorAll('.md-content.desc-rendered:not([data-rendered])').forEach(function(el) {
      el.innerHTML = marked.parse(el.textContent);
      el.setAttribute('data-rendered', '1');
    });
  }
  window.location.hash = name;
}
document.addEventListener('DOMContentLoaded', function() {
  if (typeof marked !== 'undefined') {
    document.querySelectorAll('.tab-panel.active .md-content.desc-rendered').forEach(function(el) {
      el.innerHTML = marked.parse(el.textContent);
      el.setAttribute('data-rendered', '1');
    });
  }
  var hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById('strat-tab-' + hash)) {
    switchStratTab(hash);
  }
});
