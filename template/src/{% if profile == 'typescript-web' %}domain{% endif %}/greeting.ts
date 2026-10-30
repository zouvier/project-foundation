export function greeting(name: string): string {
  const recipient = name.trim() || "friend";
  return `Hello, ${recipient}!`;
}
