document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      const original = button.textContent;
      button.textContent = button.dataset.copied;
      window.setTimeout(() => {
        button.textContent = original;
      }, 1500);
    } catch {
      window.prompt("", button.dataset.copy);
    }
  });
});
