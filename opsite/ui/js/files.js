export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(text, filename, type = "text/plain;charset=utf-8") {
  downloadBlob(new Blob([text], { type }), filename);
}

export function downloadJson(obj, filename) {
  downloadText(JSON.stringify(obj, null, 2), filename, "application/json");
}

export function pickFile(accept = ".json,application/json") {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.className = "op-visually-hidden";
    input.addEventListener("change", () => {
      resolve(input.files?.[0] || null);
      input.remove();
    });
    document.body.append(input);
    input.click();
  });
}

export const MAX_JSON_BYTES = 5 * 1024 * 1024;

export class FileError extends Error {
  constructor(message) {
    super(message);
    this.name = "FileError";
  }
}

export async function readJsonFile(file, { maxBytes = MAX_JSON_BYTES } = {}) {
  if (!file) throw new FileError("Файл не выбран");
  if (file.size > maxBytes) {
    throw new FileError("Файл слишком большой. Копия дел весит меньше 5 МБ, выберите другой файл");
  }
  let text;
  try {
    text = await file.text();
  } catch {
    throw new FileError("Не получилось прочитать файл. Попробуйте выбрать его ещё раз");
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new FileError("Это не файл копии: внутри не тот формат. Выберите файл, который сохранил инструмент");
  }
}
