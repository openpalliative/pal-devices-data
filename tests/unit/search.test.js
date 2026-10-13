import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildIndex, search, normalize, distanceAtMostOne, channelKind } from "../../lib/search.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), "utf8")).items;

const index = buildIndex({ devices: load("devices-398n"), aliases: load("aliases"), diff: load("devices-348n-diff") });
const codes = (r) => r.items.map((it) => it.code);

test("откашливатель с пробелом и с большой буквы находит 303260 первым", () => {
  for (const q of ["Откашливатель ", "откашливатель", "  ОТКАШЛИВАТЕЛЬ"]) {
    const r = search(index, q);
    assert.equal(r.items[0].code, "303260", q);
  }
});

test("кислородник даёт ровно два концентратора", () => {
  const r = search(index, "кислородник");
  assert.deepEqual([...codes(r)].sort(), ["113810", "191160"]);
});

test("памперсы дают 280360", () => {
  const r = search(index, "памперсы");
  assert.equal(r.items[0].code, "280360");
});

test("шесть цифр ищут только код", () => {
  const r = search(index, "303260");
  assert.equal(r.kind, "code");
  assert.deepEqual(codes(r), ["303260"]);
  assert.equal(search(index, "999999").kind, "empty");
});

test("код, которого нет в новом перечне, показан отдельно", () => {
  const r = search(index, "100000");
  assert.equal(r.kind, "removed");
  assert.equal(r.removed[0].code, "100000");
});

test("трубка даёт группу, а не одиночный первый результат", () => {
  const r = search(index, "трубка");
  assert.equal(r.kind, "group");
  assert.equal(r.ambiguous, true);
  assert.ok(r.groups.length >= 2);
});

test("ё и е нормализуются одинаково", () => {
  assert.equal(normalize("ёлочный"), normalize("елочный"));
  assert.equal(normalize("Кресло-коляска,  комнатная"), "кресло коляска комнатная");
});

test("опечатка в одну букву прощается в длинных бытовых названиях", () => {
  const r = search(index, "откашливатль");
  assert.equal(r.items[0].code, "303260");
  assert.equal(r.items[0].score, 30);
});

test("опечатка не прощается в коротких словах и не в бытовых названиях", () => {
  const custom = buildIndex({
    devices: [{ code: "111111", nkmi_name: "Пример", order: 1, subgroup_title: "А", channel_ids: [] },
              { code: "222222", nkmi_name: "Другое", order: 2, subgroup_title: "А", channel_ids: [] }],
    aliases: [
      { id: "zond", alias: "зонд", kind: "household", codes: ["111111"], ambiguous: false },
      { id: "ivl", alias: "аппаратик", kind: "abbr", codes: ["222222"], ambiguous: false },
    ],
  });
  assert.equal(search(custom, "зенд").kind, "empty");
  assert.equal(search(custom, "аппаротик").kind, "empty");
});

test("при точном совпадении нечёткие не показываются", () => {
  const custom = buildIndex({
    devices: [{ code: "111111", nkmi_name: "Катетер урологический", order: 1, subgroup_title: "А", channel_ids: [] },
              { code: "222222", nkmi_name: "Другое изделие", order: 2, subgroup_title: "А", channel_ids: [] }],
    aliases: [
      { id: "kateter", alias: "катетер", kind: "household", codes: ["111111"], ambiguous: false },
      { id: "kadeter", alias: "кадетер", kind: "household", codes: ["222222"], ambiguous: false },
    ],
  });
  const r = search(custom, "катетер");
  assert.deepEqual(codes(r), ["111111"]);
  assert.deepEqual(codes(search(custom, "кадетор")), ["222222"]);
});

test("поиск по слову из имени вида", () => {
  const r = search(index, "концентратор");
  assert.deepEqual([...codes(r)].sort(), ["113810", "191160"]);
  assert.equal(r.items[0].via, "name");
});

test("пустой запрос и неизвестное слово", () => {
  assert.equal(search(index, "  ").kind, "none");
  assert.equal(search(index, "абракадабра").kind, "empty");
});

test("расстояние не больше одной правки", () => {
  assert.ok(distanceAtMostOne("матрас", "матрац"));
  assert.ok(distanceAtMostOne("матрас", "матрасы"));
  assert.ok(!distanceAtMostOne("матрас", "мотрац"));
});

test("канал берётся из channel_ids", () => {
  assert.equal(channelKind({ channel_ids: ["mo-398n"] }), "mo");
  assert.equal(channelKind({ channel_ids: ["mo-398n", "sfr-pp240"] }), "both");
});

test("на настоящих данных памперсы и подгузники первыми дают взрослые", (t) => {
  const site = new URL("../../_site/data/v1/", import.meta.url);
  let real;
  try {
    const read = (n) => JSON.parse(readFileSync(new URL(`${n}.json`, site), "utf8")).items;
    real = buildIndex({ devices: read("devices-398n"), aliases: read("aliases"), diff: read("devices-348n-diff") });
  } catch {
    t.skip("сайт ещё не собран");
    return;
  }
  for (const q of ["памперсы", "подгузники"]) assert.equal(search(real, q).items[0].code, "280360", q);
});

test("больше лимита: total знает, сколько нашлось на самом деле", () => {
  const r = search(index, "кислородник", { limit: 1 });
  assert.equal(r.items.length, 1);
  assert.equal(r.total, 2);
  assert.equal(search(index, "кислородник").total, 2);
});
