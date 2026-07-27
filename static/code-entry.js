(() => {
  const digits = Array.from(document.querySelectorAll("[data-code-digit]"));
  const combined = document.querySelector("#code");

  const fillFrom = (start, value) => {
    const numbers = value.replace(/\D/g, "");
    numbers.slice(0, digits.length - start).split("").forEach((number, offset) => {
      digits[start + offset].value = number;
    });
    const next = Math.min(start + numbers.length, digits.length - 1);
    digits[next].focus();
    digits[next].select();
  };

  digits.forEach((input, index) => {
    input.addEventListener("input", () => {
      const numbers = input.value.replace(/\D/g, "");
      input.value = "";
      if (numbers) {
        fillFrom(index, numbers);
      }
    });

    input.addEventListener("paste", (event) => {
      event.preventDefault();
      fillFrom(index, event.clipboardData.getData("text"));
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Backspace" && !input.value && index > 0) {
        digits[index - 1].value = "";
        digits[index - 1].focus();
        event.preventDefault();
      } else if (event.key === "ArrowLeft" && index > 0) {
        digits[index - 1].focus();
        event.preventDefault();
      } else if (event.key === "ArrowRight" && index < digits.length - 1) {
        digits[index + 1].focus();
        event.preventDefault();
      }
    });

    input.addEventListener("focus", () => input.select());
  });

  document.querySelector("form").addEventListener("submit", () => {
    combined.value = digits.map((input) => input.value).join("");
  });
})();
