(function(){
  document.querySelectorAll("[data-password-toggle]").forEach(function(button){
    button.addEventListener("click", function(){
      const wrapper = button.closest(".password-wrap");
      if(!wrapper) return;

      const input = wrapper.querySelector("input");
      if(!input) return;

      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";
      button.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
      button.setAttribute("aria-pressed", isHidden ? "true" : "false");
    });
  });
})();
