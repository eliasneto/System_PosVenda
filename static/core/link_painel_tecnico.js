/* Admin > Links do painel técnico (2026-11-16): mostra o endereço completo do link montado pelo navegador (com a
   porta) e o botão "Copiar link". Em http (sem HTTPS) o navegador bloqueia a área de transferência: abre uma
   caixa com o link selecionado para copiar com Ctrl+C. */
(function () {
  "use strict";

  function completo(caminho) {
    return new URL(caminho, window.location.href).href;
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("a.link-painel-tecnico").forEach(function (link) {
      link.textContent = completo(link.getAttribute("href"));
    });
  });

  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest(".copiar-link-painel");
    if (!botao) {
      return;
    }
    evento.preventDefault();
    var endereco = completo(botao.getAttribute("data-href"));
    function copiado() {
      var texto = botao.textContent;
      botao.textContent = "Copiado!";
      setTimeout(function () { botao.textContent = texto; }, 2000);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(endereco).then(copiado, function () {
        window.prompt("Copie o link (Ctrl+C):", endereco);
      });
    } else {
      window.prompt("Copie o link (Ctrl+C):", endereco);
    }
  });
})();
