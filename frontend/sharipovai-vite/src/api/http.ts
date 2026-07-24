export class ApiClientError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

async function parseJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers ?? {}),
    },
  });

  const payload = await parseJson(response);
  if (!response.ok) {
    const message =
      payload &&
      typeof payload === "object" &&
      "detail" in payload &&
      typeof (payload as { detail?: unknown }).detail === "object" &&
      (payload as { detail?: { message?: string } }).detail?.message
        ? (payload as { detail: { message: string } }).detail.message
        : payload &&
            typeof payload === "object" &&
            "detail" in payload &&
            typeof (payload as { detail?: unknown }).detail === "string"
          ? (payload as { detail: string }).detail
          : "Запрос не выполнен.";
    throw new ApiClientError(message, response.status);
  }

  return payload as T;
}
