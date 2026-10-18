const form = document.getElementById("login-form");
const message = document.getElementById("login-message");

form.addEventListener("submit", async event => {
  event.preventDefault();
  message.textContent = "";
  const fields = new FormData(form);
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: fields.get("username"),
        password: fields.get("password")
      })
    });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || `${response.status} ${response.statusText}`);
    }
    await response.json();
    window.location.assign("/");
  } catch (error) {
    message.textContent = `Sign in failed: ${error.message}`;
  }
});
