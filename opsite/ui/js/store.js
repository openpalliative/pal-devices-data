import { DATABASES, PREFIXES } from "./tools.js";

const STORE = "kv";
const FORMAT = "openpalliative-backup/1";
const BLOCKED_MS = 3000;

export const BLOCKED_TEXT = "Закройте другие вкладки с инструментами и нажмите ещё раз";

export class StoreError extends Error {
  constructor(message) {
    super(message);
    this.name = "StoreError";
  }
}

function promisify(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export function deleteDatabase(idb, name, timeout = BLOCKED_MS) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => finish(reject, new StoreError(BLOCKED_TEXT)), timeout);
    const req = idb.deleteDatabase(name);
    req.onsuccess = () => finish(resolve);
    req.onerror = () => finish(reject, new StoreError("Не получилось удалить данные этого браузера"));
  });
}

function validKey(key) {
  if (typeof key === "string") return key.length > 0 && key.length <= 200;
  return typeof key === "number" && Number.isFinite(key);
}

export function validateBackup(backup, repo) {
  if (!backup || typeof backup !== "object" || Array.isArray(backup) || backup.format !== FORMAT) {
    throw new StoreError("Это не файл копии openpalliative. Выберите файл, который сохранил этот инструмент");
  }
  if (backup.repo !== repo) throw new StoreError("Это копия другого инструмента. Откройте её там, где сохраняли");
  if (!Array.isArray(backup.entries)) throw new StoreError("Файл копии повреждён: в нём нет списка записей");
  return backup.entries.map((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry) || !("value" in entry)) {
      throw new StoreError("Файл копии повреждён: запись не в том виде");
    }
    if (!validKey(entry.key)) throw new StoreError("Файл копии повреждён: у записи неверный ключ");
    return { key: entry.key, value: entry.value };
  });
}

export function openStore(repo, { indexedDB: idb = globalThis.indexedDB } = {}) {
  const name = `op-${repo}`;
  let dbPromise = null;

  function db() {
    if (!dbPromise) {
      const req = idb.open(name, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      dbPromise = promisify(req).then((d) => {
        d.onversionchange = () => {
          d.close();
          dbPromise = null;
        };
        return d;
      });
      dbPromise.catch(() => {
        dbPromise = null;
      });
    }
    return dbPromise;
  }

  function done(t) {
    return new Promise((resolve, reject) => {
      t.oncomplete = resolve;
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error || new StoreError("Запись прервана, данные не изменились"));
    });
  }

  async function tx(mode, fn) {
    const d = await db();
    const t = d.transaction(STORE, mode);
    const result = fn(t.objectStore(STORE));
    await done(t);
    return result instanceof IDBRequest ? result.result : result;
  }

  return {
    name,
    get: (key) => tx("readonly", (s) => s.get(key)),
    set: (key, value) => tx("readwrite", (s) => s.put(value, key)),
    delete: (key) => tx("readwrite", (s) => s.delete(key)),
    async list() {
      const d = await db();
      const t = d.transaction(STORE, "readonly");
      const s = t.objectStore(STORE);
      const [keys, values] = await Promise.all([promisify(s.getAllKeys()), promisify(s.getAll())]);
      return keys.map((key, i) => ({ key, value: values[i] }));
    },
    async exportAll() {
      const entries = await this.list();
      return { format: FORMAT, repo, exported_at: new Date().toISOString(), entries };
    },
    async importAll(backup, { replace = false } = {}) {
      const entries = validateBackup(backup, repo);
      const d = await db();
      const t = d.transaction(STORE, "readwrite");
      const s = t.objectStore(STORE);
      if (replace) s.clear();
      for (const { key, value } of entries) s.put(value, key);
      await done(t);
      return entries.length;
    },
    async wipe({ timeout } = {}) {
      if (dbPromise) (await dbPromise.catch(() => null))?.close();
      dbPromise = null;
      await deleteDatabase(idb, name, timeout);
    },
  };
}

export async function wipeAll({
  indexedDB: idb = globalThis.indexedDB,
  storage = globalThis.localStorage,
  caches: cacheStorage = globalThis.caches,
  serviceWorker = globalThis.navigator?.serviceWorker,
  timeout = BLOCKED_MS,
} = {}) {
  let removed = 0;
  if (storage) {
    for (const key of Object.keys(storage)) {
      if (PREFIXES.some((p) => key.startsWith(`${p}:`))) {
        storage.removeItem(key);
        removed += 1;
      }
    }
  }
  if (cacheStorage?.keys) {
    for (const key of await cacheStorage.keys()) {
      await cacheStorage.delete(key);
      removed += 1;
    }
  }
  if (serviceWorker?.getRegistrations) {
    for (const reg of await serviceWorker.getRegistrations()) {
      await reg.unregister().catch(() => false);
    }
  }
  if (idb) {
    const names = new Set(DATABASES);
    if (idb.databases) {
      for (const info of await idb.databases().catch(() => [])) {
        if (info.name?.startsWith("op-")) names.add(info.name);
      }
    }
    for (const name of names) {
      await deleteDatabase(idb, name, timeout);
      removed += 1;
    }
  }
  return removed;
}
