export function authErrorMessage(error: unknown): string {
  const raw =
    error && typeof error === "object" && "message" in error
      ? String((error as { message: unknown }).message)
      : typeof error === "string"
        ? error
        : "";
  const text = raw.toLowerCase();

  if (!raw) {
    return "We couldn’t complete sign-in. Please try again.";
  }
  if (
    text.includes("invalid login") ||
    text.includes("invalid credentials") ||
    text.includes("invalid email or password") ||
    text.includes("email not confirmed") ||
    text.includes("user not found") ||
    text.includes("wrong")
  ) {
    return "We couldn’t sign you in. Check your email and password and try again.";
  }
  if (text.includes("already registered") || text.includes("already exists")) {
    return "An account with this email already exists. Try logging in.";
  }
  if (
    text.includes("network") ||
    text.includes("failed to fetch") ||
    text.includes("fetch")
  ) {
    return "Something went wrong. Check your connection and try again.";
  }
  if (text.includes("oauth") || text.includes("provider") || text.includes("popup")) {
    return "We couldn’t complete sign-in. Please try again.";
  }
  return "We couldn’t complete sign-in. Please try again.";
}

export function passwordResetMessage(error: unknown): string {
  if (!error) return "";
  return "We couldn’t send a reset email. Check the address and try again.";
}
