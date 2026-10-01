# Проверка фактов по вики

Источник один: **bg3.wiki**. Не по памяти, не из настольной D&D 5e.

---

## 1. Рабочий способ: curl со стриппером тегов

Один копируемый блок. Подставить имя страницы вместо `<Page>`.

```bash
curl -sL "https://bg3.wiki/wiki/<Page>" | python3 -c "
import sys,re,html
t=sys.stdin.read()
t=re.sub(r'<script.*?</script>','',t,flags=re.S)
t=re.sub(r'<style.*?</style>','',t,flags=re.S)
t=re.sub(r'<[^>]+>',' ',t)
t=html.unescape(t)
t=re.sub(r'[ \t]+',' ',t)
t=re.sub(r'\n\s*\n+','\n',t)
i=t.find('From bg3.wiki')
print(t[i:i+4000])
"
```

Много страниц за один вызов:

```bash
for s in Cone_of_Cold Cloudkill Lightning_Bolt Ice_Storm Mirror_Image Haste
do
  echo "===== $s ====="
  curl -sL "https://bg3.wiki/wiki/$s" | python3 -c "
import sys,re,html
t=sys.stdin.read()
t=re.sub(r'<script.*?</script>','',t,flags=re.S)
t=re.sub(r'<style.*?</style>','',t,flags=re.S)
t=re.sub(r'<[^>]+>',' ',t)
t=html.unescape(t)
t=re.sub(r'[ \t]+',' ',t)
t=re.sub(r'\n\s*\n+','\n',t)
i=t.find('From bg3.wiki')
print(t[i:i+3000])
"
done
```

Именно так получены дословные технические строки, которых иначе не было:
`5d8 Poison damage per turn ... Constitution Saving Throw to halve`,
`Encrusted with Frost ... Disadvantage on Dexterity Saving Throws ... When there
are 7 or more turns remaining ... DC 12 Constitution Saving Throw or ... become
Frozen`, `Lightning Charges ... +1 to Attack Rolls and deal an additional 1
Lightning damage ... If you gain 5 charges, they are consumed the next time you
deal damage ... 1d8`.

## 2. Сырой wikitext, когда рендер таблицы врёт

Рендер таблиц с rowspan парсится неверно. Таблица прогрессии класса
(«уровень → сколько фокусов и известных заклинаний») читается только так:

```bash
curl -sL "https://bg3.wiki/wiki/Sorcerer?action=raw"
```

Через API то же самое:

```bash
curl -sL "https://bg3.wiki/w/api.php?action=parse&page=Sorcerer&prop=wikitext&format=json"
```

Оба пути проверены. **Внимание на префикс `/w/`**: у bg3.wiki api лежит по
`/w/api.php`, а не по `/api.php`, и `index.php` тоже по `/w/`. Без префикса
приходит 404 от nginx, и это легко принять за отсутствие страницы.

Применять всегда, когда вывод зависит от таблицы «что доступно на каком уровне».
Ошибка «взять метамагию A и B» прожила две версии файла именно потому, что
таблица доступности не сверялась: обе открываются с 3 уровня, а пик на 3 уровне
один, вместе они собираются только к 10.

## 3. Почему не WebFetch

WebFetch пересказывает и теряет технические поля. Симптом это ответ
«the page does not specify». Он встретился по трём страницам, и минимум на двух
из них curl показывал ответ прямо в инфобоксе.

**Ответ «страница не уточняет» это сигнал перечитать через curl, а не вывод.**

---

## 4. Заблокировано и ломается

| Источник | Что происходит |
|---|---|
| reddit.com | WebSearch с `allowed_domains:["reddit.com"]` даёт `400 The following domains are not accessible to our user agent`. WebFetch по old.reddit.com отказывает. Обхода нет |
| nexusmods.com | HTTP 403 Forbidden |
| facebook.com | отдаёт только заголовок поста, тела нет |
| baldursgate3.fandom.com, bg3.fandom.com | не существуют, «This wiki does not exist» |
| baldursgate.fandom.com через curl | 403 Cloudflare даже с браузерным User-Agent. Только браузерный инструмент, см. `localization.md` |

Игрок дважды просил «погугли на редите». Отвечать прямо: Reddit недоступен,
смотрю в других местах.

Замены, которые реально сработали: **Steam Community, форумы Larian, Fextralife,
Game8, Gamer Guides, TheGamer, GameRant**.

## 5. Страницы-ловушки

| Что просится | Что на самом деле |
|---|---|
| `Myrkul,_Lord_of_Bones` | 404, нужна `Apostle_of_Myrkul` |
| `Shield` | страница-дизамбиг, нужна `Shield_(spell)` |
| `Poison_Immunity` | страницы не существует, смотреть `Category:Immune_to_all_Poison` |
| `Point_of_no_return` | 404 |

Общее правило: 404 или дизамбиг это не «в игре такого нет», а неверное имя
страницы. Искать через `?search=` на самой вики, прежде чем делать вывод.

## 6. Какую страницу открывать

- **Механику условия читать на странице условия, а не заклинания.** Страница
  заклинания её не содержит. Так нашлось, что Корка льда стакается по
  длительности и при 7 и более оставшихся ходах бросает цель в Заморожен.
- **Открывать страницы предметов, а не только заклинаний.** Предмет может
  раздавать заклинания бесплатно раз за короткий отдых и переворачивать весь
  расчёт по кругу. Заклинание, которое даёт предмет, в известные не берётся.
- **Прежде чем сказать «иммунитетов к типу X нет», открыть**
  `Category:Immune_to_all_<Type>` и `Category:Resistant_to_all_<Type>`.
  По молнии это 18 иммунных существ и 82 устойчивых.
- **Для всего, у чего есть «заряды» или «копии», отдельно читать условие расхода
  заряда.** Копии Зеркального отражения исчезают при **промахе**, а не при
  попадании, и это меняет оценку в разы.

## 7. Полезные страницы

Механики: `Wet_(Condition)`, `Encrusted_with_Frost_(Condition)`,
`Paralysed_(Condition)`, `Petrified_(Condition)`, `Lightning_Charges`,
`Electrified_Water`, `Karmic_Dice`, `Trading`, `Metamagic`,
`Metamagic:_Careful_Spell`, `List_of_sources_of_resistances`.

Категории: `Category:Immune_to_all_Lightning`, `Category:Resistant_to_all_Lightning`.

Классовое: `Sorcerer`, `Wizard`, `Cleric`, `War_Caster`.

## 8. Шаблоны поисковых запросов

- Точное английское имя предмета + `bg3` → Fextralife, Game8, Deltia
- `larian forums OR steamcommunity "<точная фраза>" bug` → треды про баги
- `BG3 <название механики> how it works` → гайд-сайты с разбором
- Запросы **по-русски бесполезны для проверки фактов**: выдают только фанатские
  перепечатки. По-русски ищется только локализованное название, см.
  `localization.md`

## 9. Цикл режима fact

1. Открыть страницу через curl со стриппером
2. Привести **дословную цитату** нужной строки, английскую
3. Дать вердикт одной фразой
4. Если строки на странице нет, сказать «на странице этого нет» и назвать, где
   ещё смотрел. Не достраивать по смыслу и не переносить правило из настольной 5e
