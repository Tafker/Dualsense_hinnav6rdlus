# Klick – otsingukaardi väljad

**Pood:** Klick  
**Otsing:** `Sony juhtmevaba mängupult PlayStation 5 DualSense, valge`  
**URL-näide (otsinguleht):** https://www.klick.ee/search/Sony%20juhtmevaba%20m%C3%A4ngupult%20PlayStation%205%20DualSense%2C%20valge

---

## [Tootekaardi konteiner]
- **Element (silt + klass):** `<li>` *(kui näed klassi, täpsusta nt `<li class="…">`; oluline, et kataks pilt+nimi+hind)*
- **Miks stabiilne:** sama struktuur kõikidel kaartidel; sees on nimi ja hind

---

## [Nimetus + link]
- **Element:** `<a><span>Toote nimi</span></a>`
- **Nimetus (tekst):** Sony juhtmevaba mängupult PlayStation 5 DualSense, valge
- **Link (href):**  
  https://www.klick.ee/sony-juhtmevaba-mangupult-playstation-5-dualsense-valge-1  
  *(Märkus: HTML-is võib `&` olla kujul `&amp;` — OK.)*

---

## [Hind]
- **Elemendi kirjeldus (silt/klass):** `<div class="kuSalePrice">` *(otsene hinnatekst; vanem konteiner: `<div class="kuPrice">`)*
- **Näidisväärtus (copy lehelt):** 94,99 €
- **Struktuurinõks:** DOM-is võib väärtus olla kujul `94.99&nbsp;` ja € eraldi; hiljem normaliseerin → `94.99`
- **(Valikuline) OuterHTML (lühike):**
```html
<div class="kuPrice">
  <div class="kuSalePrice">94.99&nbsp;</div>
</div>



---

## [Soodushind] (kui on)
- **Elemendi kirjeldus: puudub
- **Näidisväärtus: puudub

---

## [Rating] (kui on)
- Tüüp: number
- Elemendi kirjeldus (silt/klass): puudub
- **Näidisväärtus: puudub

---

## [Pood]
- **Püsiv tekst:** Klick

---

## [Märkused]
- Hinnad: hiljem eemaldan `€` ja tühikud; **koma → punkt** (nt `94,90` → `94.90`).
- Link: kui oleks suhteline (algaks `/`), lisan ette `https://www.klick.ee`.
- Vajadusel kerin alla, et kaardid DOM-i ilmuksid.
