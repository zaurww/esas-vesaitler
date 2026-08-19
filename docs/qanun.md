# Правовая основа — выдержки из Налогового кодекса АР

Дословный текст статей, на которых держится движок. Записан в репозиторий
намеренно: без него таблица ставок в `engine/rates.py` — набор чисел без
источника, и проверить её нельзя ни мне, ни проверяющему.

**Источник:** «Azərbaycan Respublikasının Vergi Məcəlləsi»,
<https://www.taxes.gov.az/files/2/vergi-mecellesi/VM_new2019.pdf>
Извлечено 13.08.2026.

> ⚠️ Это не заверенная копия и **редакция не сверена с действующей**
> (CLAUDE.md §12.2). Перед сдачей отчётности сверяйтесь с taxes.gov.az
> или e-qanun.az.
>
> Исключение — **115.3, 115.6 и 115.6-1**: сверены 19.08.2026 по
> `D:\consulting\legal-base\tax\current\-Azərbaycan Respublikasının Vergi
> Məcəlləsi.md` (сводный текст с разметкой правок и датами законов), тем же
> путём, каким CLAUDE.md §12 велит сверять то, чего нет в этом файле.
> Извлечение от 13.08.2026 выше **не содержало ст. 115.6-1 вовсе** —
> редакция 406-VIQD/1033-VIQD в него не попала.

---

## Что где реализовано

| норма | что говорит | где в коде |
|---|---|---|
| 114.2 | что не амортизируется (земля, искусство, законсервированное, склад) | **не реализовано** — вне области §1 |
| 114.3 | годовые нормы по категориям, «faizədək» = **до** N% | `engine/rates.py` `STATUTORY_RATES` |
| 114.3-1 | микро — коэффициент 2, «hüququna malikdirlər» (право) | `rates.py` `MULTIPLIERS`, опционально через `taxpayer_status.use_coefficient` |
| 114.3-2 | малый — коэффициент 1,5 | там же |
| 114.4 абз.1 | норма применяется к остатку **категории** | `calc.py`, шаг 6 конвейера |
| 114.4 абз.2 | недоиспользованная норма переносится на будущие годы | **не реализовано** — §12.4-bis |
| 114.5 | по зданиям — раздельно по каждому объекту | покарточный метод покрывает |
| 114.6 | формула базы: остаток + поступления + ремонт сверх лимита − выбывшие/подпороговые | `calc.py`, шаги 1–4 |
| 114.6 посл. | прирост от переоценки в базу **не** входит | переоценки нет — вне области §1 |
| 114.7 | выручка > остатка → разница **в доход** | `calc.py` `disposal_gain` |
| 114.8 | остаток на конец года < 500 или < 5% → **вычитается из дохода** | `calc.py` `threshold_test`, см. §5.3-bis |
| 114.9 | выручка < остатка → разница **из дохода** | `calc.py` `disposal_loss` |
| 114.10 | госпредприятия на бюджетные инвестиции — только 40% | **не реализовано** — вне области §1 |
| 115.1 | лимит ремонта: 2% / 5% / 3% по ссылкам на 114.3.x | `rates.py` `repair_limit` |
| 115.1 абз.2 | неиспользованный лимит увеличивает лимит будущих лет | **не реализовано** — §12.4-bis |
| 115.2 | превышение лимита увеличивает остаток на конец года | `calc.py`, шаг 3 |
| 115.3 | диапазон 115.4–115.6-1 (сужен законом 406-VIQD от 03.12.2021; было 115.4–115.8) | категория `it` — только ветка 115.6-1, см. ниже |
| 115.4 | арендованное ОС **на балансе арендатора** — процентный лимит по типу объекта | **не реализовано** — сознательно вне области, CLAUDE.md §5.1, §10 (19.08.2026) |
| 115.6-1 | арендованное ОС **не на балансе**, расход не возмещён/не зачтён в счёт аренды — амортизация по сроку договора, не менее 5 лет, каждый год ремонта отдельно | категория `it`, `method="duz"`, **реализовано 19.08.2026** — CLAUDE.md §5.1, §10 |
| 115.7 | если остаток категории нулевой — ремонт целиком в остаток | **не реализовано** — §12.4-ter |
| 144.1.3 | разница не признаётся при недобровольном выбытии с реинвестированием | не применяется автоматически, поднимается вопросом при `leqv` |

Категории кодекса, которых нет в движке: **114.3.4** (iş heyvanları, 20%),
**114.3.5** (geoloji-kəşfiyyat, 25%). Категория `ym` (грузовики) в кодексе
отдельной не существует — это 114.3.3.

---

## Maddə 114. Amortizasiya ayırmaları və gəlirdən amortizasiya olunan aktivlər üzrə çıxılan məbləğlər

**114.1.** Bu Məcəllənin 99-cu maddəsində müəyyən edilmiş sahibkarlıq və qeyri-sahibkarlıq fəaliyyətində istifadə edilən əsas vəsaitlər üzrə amortizasiya ayırmaları bu maddənin müddəalarına uyğun olaraq gəlirdən çıxılır.

**114.2.** Torpaq, incəsənət əsərləri, nadir tarixi və memarlıq abidələri olan binalar, qurğular (tikililər) və bu maddə ilə müəyyən edilən köhnəlməyə məruz qalmayan digər aktivlər amortizasiya olunmur:

**114.2.1.** elmi-tədqiqat, tədris və təcrübə məqsədi üçün kabinetlərdə və laboratoriyalarda istifadə edilən avadanlıqlar, eksponatlar, nümunələr, fəaliyyətdə olan və olmayan modellər, maketlər və başqa əyani vəsaitlər;

**114.2.2.** məhsuldar heyvanlar (damazlıq inəklər, camışlar, madyanlar, dəvələr, marallar, donuzlar, qoyunlar, keçilər, döllük buğalar, kəllər, ayğırlar, nərlər, qabanlar, qoçlar, təkələr və bunlar kimi digər məhsuldar heyvanlar);

**114.2.3.** heyvanxanalarda və digər analoji müəssisələrdə olan heyvanat aləminin eksponatları;

**114.2.4.** istismar vaxtı çatmayan çoxillik əkmələr;

**114.2.5.** kitabxana fondları, kinofondlar (video, audio, foto), səhnə rekvizitləri, muzey sərvətləri (eksponatları);

**114.2.6.** tam amortizasiya olunmuş əsas vəsaitlər, onlar istismara yararlı olduğu hallarda;

**114.2.7.** konservasiya edilmiş əsas vəsaitlər;

**114.2.8.** ümumi istifadədə olan avtomobil yolları;

**114.2.9.** ümumi istifadədə olan parklardakı avadanlıqlar;

**114.2.10.** istismara verilməmiş anbarda olan əsas vəsaitlər.

**114.3.** Amortizasiya olunan aktivlər üzrə illik amortizasiya normaları aşağıdakı kimi müəyyən edilir:

**114.3.1.** binalar, tikililər və qurğular - 7 faizədək;

**114.3.2.** maşınlar və avadanlıq - 20%-dək;

**114.3.2-1.** yüksək texnologiyalar məhsulu olan hesablama texnikası üzrə - 25 faizədək;

**114.3.3.** nəqliyyat vasitələri - 25 faizədək;

**114.3.4.** iş heyvanları - 20 faizədək;

**114.3.5.** geoloji-kəşfiyyat işlərinə və təbii ehtiyatların hasilatına hazırlıq işlərinə çəkilən xərclər - 25 faizədək;

**114.3.6.** qeyri-maddi aktivlər - istifadə müddəti məlum olmayanlar üçün 10 faizədək, istifadə müddəti məlum olanlar üçün isə illər üzrə istifadə müddətinə mütənasib məbləğlərlə;

**114.3.7.** digər əsas vəsaitlər - 20 faizədək;

**114.3.8.** (Azərbaycan Respublikasının 21 oktyabr 2005-ci il tarixli 1028-IIQD nömrəli Qanunu ilə ləğv edilmişdir).

**114.3-1.** Mikro sahibkarlıq subyektləri sahibkarlıq fəaliyyətində istifadə etdikləri əsas vəsaitlərə münasibətdə amortizasiya ayırmalarını bu Məcəllənin 114.3-cü maddəsi ilə müəyyən edilən amortizasiya normalarına 2 əmsal tətbiq etməklə gəlirdən çıxmaq hüququna malikdirlər.

**114.3-2.** Kiçik sahibkarlıq subyektləri sahibkarlıq fəaliyyətində istifadə etdikləri əsas vəsaitlərə münasibətdə amortizasiya ayırmalarını bu Məcəllənin 114.3-cü maddəsi ilə müəyyən olunmuş amortizasiya normalarına 1,5 əmsal tətbiq etməklə gəlirdən çıxmaq hüququna malikdirlər.

**114.4.** Əsas vəsaitlərin kateqoriyaları üzrə amortizasiya ayırmaları bu Məcəllənin 114.3-cü maddəsi ilə hər kateqoriyaya aid olan əsas vəsaitlər üçün müəyyənləşdirilmiş amortizasiya normasını həmin kateqoriyaya aid əsas vəsaitlərin vergi ilinin sonuna qalıq dəyərinə tətbiq etməklə hesablanır. Hər hansı kateqoriyaya aid olan əsas vəsaitlər üzrə vergi ili üçün müəyyən olunmuş amortizasiya normalarından aşağı norma tətbiq olunduqda, bunun nəticəsində yaranan fərq növbəti vergi illərində amortizasiyanın gəlirdən çıxılan məbləğinə əlavə oluna bilər.

**14.5.** Binalar, tikililər və qurğular (bundan sonra - tikililər) üçün amortizasiya ayırmaları hər tikili üzrə ayrılıqda aparılır.

**114.6.** Amortizasiya hesablanması məqsədləri üçün əsas vəsaitlər (vəsait) üzrə vergi ilinin sonuna qalıq dəyəri aşağıdakı qaydada müəyyənləşdirilən (lakin sıfırdan aşağı olmayan) məbləğdən ibarət olur: əsas vəsaitlərin (vəsaitin) əvvəlki ilin sonuna qalıq dəyərinə (həmin il üçün hesablanmış amortizasiya məbləği çıxıldıqdan sonra qalan dəyər) bu Məcəllənin 143-cü maddəsinə uyğun olaraq cari ildə daxil olmuş əsas vəsaitlərin (vəsaitin) dəyəri, habelə cari ildə bu Məcəllənin 115-ci maddəsinə əsasən müəyyən edilən təmir xərclərinin məhdudlaşdırmadan artıq olan hissəsi əlavə edilir, vergi ilində təqdim edilmiş, ləğv edilmiş və ya qalıq dəyəri 500 manatdan və ya ilkin dəyərin 5 faizindən az olduqda əsas vəsaitlərin qalıq dəyəri çıxılır. Əsas vəsaitlərin (vəsaitin) yenidən qiymətləndirilməsindən yaranan artım (yenidən qiymətləndirilmə nəticəsində yaranan müsbət fərq) amortizasiya hesablanması məqsədləri üçün əsas vəsaitlərin (vəsaitin) vergi ilinin sonuna qalıq dəyərinə əlavə olunmur.

**114.7.** Əsas vəsaitlərin (vəsaitin) təqdim edilməsindən əldə olunan məbləğ həmin əsas vəsaitlərin (vəsaitin) qalıq dəyərindən artıqdırsa, yaranmış fərq gəlirə daxil edilir.

**114.8.** İlin sonuna əsas vəsaitin qalıq dəyəri 500 manatdan və ya ilkin dəyərinin 5 faizindən az olduqda, qalıq dəyərinin məbləği gəlirdən çıxılır.

**114.9.** Əsas vəsaitlərin (vəsaitin) təqdim edilməsindən əldə olunan məbləğ, həmin əsas vəsaitlərin (vəsaitin) qalıq dəyərindən azdırsa, yaranmış fərq gəlirdən çıxılır.

**114.10.** Bu maddənin digər müddəalarından asılı olmayaraq, dövlət müəssisələrinə dövlət büdcəsinin investisiya xərcləri hesabına ayrılmış vəsaitlər hesabına alınan və ya quraşdırılan aktivlərin, bu Məcəllənin 114.3-cü maddəsi ilə müəyyən olunmuş illik amortizasiya normalarına uyğun hesablanmış amortizasiyanın yalnız 40 faizi gəlirdən çıxılır.

## Maddə 115. Təmirlə bağlı xərclərin gəlirdən çıxılması

**115.1.** Hər il üçün gəlirdən çıxılmalı olan təmir xərclərinin məbləği əsas vəsaitlərin hər bir kateqoriyasının əvvəlki ilin sonuna qalıq dəyərinə müvafiq olaraq bu Məcəllənin 114.3.1-ci maddəsində göstərilən əsas vəsaitlərin kateqoriyasının ilin sonuna qalıq dəyərinin 2 faizi, 114.3.2-ci və 114.3.3-cü maddələrində göstərilən əsas vəsaitlərin kateqoriyasının ilin sonuna qalıq dəyərinin 5 faizi, 114.3.7-ci maddəsində göstərilən əsas vəsaitlərin kateqoriyasının ilin sonuna qalıq dəyərinin 3 faizi və köhnəlmə (amortizasiya) hesablanmayan əsas vəsaitlər üzrə sıfır (0) faizi həddi ilə məhdudlaşdırılır. Təmir xərclərinin faktiki məbləği bu hədd ilə müəyyənləşdirilən məbləğdən az olduqda, gəlirdən təmir xərclərinin faktiki məbləği çıxılır. Bu halda növbəti vergi illərində təmir xərclərinin gəlirdən çıxılan məbləğ həddi təmir xərclərinin faktiki məbləği ilə müəyyənləşdirilmiş hədd üzrə hesablanmış məbləği arasındakı fərq qədər artırılır.

**115.2.** Bu Məcəllənin 115.1-ci maddəsində müəyyən edilən məhdudlaşdırmadan artıq olan məbləğ cari vergi ilinin sonuna əsas vəsaitlərin (vəsaitin) qalıq dəyərinin artmasına aid edilir. Amortizasiya olunmayan, köhnəlmə (amortizasiya) hesablanmayan əsas vəsaitlərin təmirinə çəkilmiş xərclər gəlirdən çıxılmır və onların balans dəyərini artırır.

**115.3.** İcarəyə götürülmüş əsas vəsaitlər üzrə təmir xərclərinin gəlirdən çıxılması bu Məcəllənin 115.4 - 115.6-1-ci maddələrinə uyğun olaraq müəyyən edilir. *(Redaksiya 406-VIQD, 03.12.2021 — əvvəllər "115.4-115.8-ci" idi; 115.7 və 115.8 artıq icarəyə aid deyil.)*

**115.4.** İcarəyə götürülmüş əsas vəsaitlərin təmiri üzrə xərclərin gəlirdən çıxılan məbləği əsas vəsaitlərin hər bir kateqoriyasının əvvəlki ilin sonuna qalıq dəyərinin bu Məcəllənin 115.1-ci maddəsi ilə müəyyən edilən faiz həddi ilə məhdudlaşdırılır.

**115.5.** Əsas vəsaitlərin icarəyə götürülməsi müddətləri, şərtləri, habelə onların təmiri üzrə xərclər qanunvericilikdə nəzərdə tutulmuş qaydada icarəyə verənlə icarəçi arasında bağlanılan müqavilədə razılaşdırılır.

**115.6.** İcarəyə götürülmüş əsas vəsaitlər icarəçinin balansında uçota alınmadıqda və ya təmir işləri icarəyə verənin hesabına aparıldıqda, yaxud icarəçinin hesabına aparılaraq, icarə haqqı ilə əvəzləşdirildikdə bu Məcəllənin 115.4-cü maddəsinin müddəaları icarəçiyə tətbiq edilmir. *(Redaksiya 1033-VIQD, 05.12.2023 — "İcarəyə götürülmüş əsas vəsaitlər icarəçinin balansında uçota alınmadıqda və ya" hissəsi və "115.4-cü maddəsinin" sözləri əlavə/dəyişdirilib.)*

**115.6-1.** İcarəçinin balansında uçota alınmayan əsas vəsaitlərin təmirinə çəkilən və icarə haqqı ilə əvəzləşdirilməyən, yaxud icarəyə verən tərəfindən əvəzi ödənilməyən xərclər bağlanmış müqavilə müddəti ərzində, lakin 5 ildən az olmayaraq, illər üzrə mütənasib məbləğlərdə amortizasiya olunmaqla gəlirdən çıxılır. İcarəyə götürülmüş əsas vəsaitlərin təmirinə çəkilən xərclər hər il üzrə ayrıca olaraq kapitallaşdırılır və bu maddə ilə müəyyən edilmiş qaydada amortizasiya olunur. *(Əlavə edilib 406-VIQD, 03.12.2021; yeni redaksiyada — 1033-VIQD, 05.12.2023. Mühərrikdə: kateqoriya `it`, yalnız bu maddə — CLAUDE.md §5.1, §10.)*

**115.7.** Əsas vəsaitlərin hər bir kateqoriyasının ilin sonuna qalıq dəyəri sıfıra bərabər olduqda, təmir xərclərinin faktiki məbləği müvafiq kateqoriyaya aid əsas vəsaitlərin qalıq dəyərinə aid edilir və bu Məcəllənin müddəalarına uyğun olaraq amortizasiya hesablanır.

**115.8.** Bu Məcəllənin müddəaları yalnız təmir xərclərinin gəlirdən çıxılan məbləğini məhdudlaşdırır və vergi ödəyicilərinin digər mənbələr hesabına təmir işlərini həyata keçirməsini qadağan etmir.

## Maddə 144. Gəlirin və ya zərərin qəbul edilməməsi

**144.1.** Vergi tutulan gəlir müəyyən edilərkən aşağıdakı hallarda gəlir və ya zərər nəzərə alınmır:

**144.1.1.** aktivlər ər və arvad arasında verildikdə;

**144.1.2.** aktivlər keçmiş ər-arvad arasında boşanma prosesində verildikdə;

**144.1.3.** aktivin ləğv edildiyi, yaxud özgəninkiləşdirildiyi ildən sonrakı ilin axırınadək daxilolmaları analoji aktivə və ya eyni xarakterli aktivə təkrar investisiya etməklə aktiv qərəzsiz, yaxud onun sahibinin iradəsindən asılı olmayaraq məhv edildikdə, ləğv olunduqda və ya özgəninkiləşdirildikdə.

**144.2.** Bu Məcəllənin 144.1.3-cü maddəsində göstərilən əvəzedici aktivin dəyəri əvəz olunan aktivin məhv edildiyi, ləğv olunduğu və ya təqdim edildiyi vaxtdakı ilk dəyəri nəzərə alınmaqla müəyyənləşdirilir.

**144.3.** Bu Məcəllənin 144.1.1-ci və ya 144.1.2-ci maddələrinə uyğun olaraq mənfəətin vergi məqsədləri üçün nəzərə alınmadığı əqdin nəticəsində alınan aktivin dəyəri əqd günündə onu verən tərəf üçün də aktivin dəyəri sayılır.

**144.4.** (Azərbaycan Respublikasının 26 noyabr 2002-ci il tarixli 383-IIQD nömrəli Qanunu ilə çıxarılmışdır).

