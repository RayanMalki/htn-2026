export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg;
    throw new Error(message || `Request failed (${response.status}). Please try again.`);
  }
  return response.json();
}

export const finished = (status: string) => ['complete', 'incomplete', 'no_claims'].includes(status);
export function seconds(value: number) { return `${Math.round(value)}s`; }
