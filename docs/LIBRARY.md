# دليل المكتبة: إزاي تضيف قطاع وخاماته ونماذجه وتخصيماته

المكتبة العامة بتتسجل **مرة واحدة** بحساب MYTech (شركة النظام)، وبعد كده تتباع لأي عميل من غير ما تتدخل تاني:
- **أونلاين:** كل الشركات بتشوفها على طول بعد النشر.
- **أوفلاين:** بتصدّرها كحزمة، توقّعها، والعميل يستوردها (التفاصيل في آخر الملف).

ممكن تعمل ده من الواجهة (لما تتعمل) أو من `/api/docs` مباشرة. أي شركة كمان تقدر تعمل قطاعات خاصة بيها بنفس الخطوات، ودي محدش غيرها بيشوفها.

## 0) حساب MYTech
```
python -m app.cli create-platform-admin --username vendor
```
وبعدين ادخل بـ `company_code: "__platform__"`.

## 1) السيستم
```json
POST /api/v1/library/systems
{"code": "KOMBIN-SL", "name": "كومبن جرار", "supplier": "كومبن", "material_type": "upvc",
 "unit": "cm", "rounding_step_mm": "0.5", "rounding_mode": "half_up", "status": "trial", "image_id": "..."}
```
- `unit`: الوحدة اللي هتكتب بيها المعادلات (`cm` أو `mm`)، والمفضّل `cm`.
  - **الواجهة بتعرض وبتستقبل كل المقاسات بالسنتيمتر** (إعداد الشركة `length_unit`، والافتراضي `cm`).
  - الـ API نفسه بيتعامل بالمليمتر عشان الدقة، وبرنامج الديسكتوب بيحوّل.
  - **في أي مقاس: العرض الأول وبعده الارتفاع.**
- `rounding_step_mm` و`rounding_mode`: تقريب أطوال القطع والزجاج في الآخر (مثلًا لأقرب 0.5 مم، `half_up` أو `up` أو `down`). صفر يعني من غير تقريب.
- `status`: `trial` (تحت التجربة، وأي حساب بيطلع عليه تحذير) أو `approved` (معتمد).
- `material_type` بيحدد الرخصة المطلوبة (`mfg.upvc` / `mfg.shutter` / `mfg.aluminum`). العميل مابيشوفش غير السيستمات اللي هو مرخّص ليها.

أي سيستم جديد بيتعمل معاه أوتوماتيك الثابتين **`install_clearance_width`** و**`install_clearance_height`** (خلوص التركيب، قيمتهم الافتراضية 0). عدّلهم بالقيمة الصح.

## 2) الثوابت
كل ثابت ليه اسم واضح، والمعادلات بتتكتب بالأسامي دي. الاسم حروف (عربي أو إنجليزي) وأرقام و`_`، ومايبدأش برقم.
```json
POST /api/v1/library/systems/{id}/constants
{"name": "weld_allowance", "label": "سماحية اللحام", "value": "0.3", "unit": "cm"}
{"name": "sash_overlap_total", "label": "ركوب الضلف (إجمالي)", "value": "8.2", "unit": "cm"}
{"name": "glass_deduction", "label": "خصم الزجاج من الضلفة", "value": "13", "unit": "cm"}
```

## 3) الخامات
```json
POST /api/v1/library/materials
{"system_id": "...", "code": "KP-WG6", "name": "حلق جرار 3 مجرى ببرور 3.8", "category": "قطاعات",
 "kind": "profile", "unit": "m", "bar_length_mm": "6000", "min_piece_mm": "250", "weight_kg_per_m": "1.1",
 "reference_cost": "95", "image_id": "...",
 "variants": [{"color_code": "W", "sku": "KP-WG6W", "name": "أبيض"},
              {"color_code": "B", "sku": "KP-WG6B", "name": "بيج"}]}
```
- `kind`: profile (قطاع) / reinforcement (حديد) / accessory / glass / gasket / consumable / panel / other.
- `unit`: m / pcs / set / roll / m2 / kg / l.
- `bar_length_mm` بيُستخدم في تحسين التقطيع، و`min_piece_mm` بيرفض أي قطعة أقصر منه.
- `variants`: كود SKU لكل لون. أمر الشغل بيختار الـ SKU حسب لون الشباك.
- الخامات المشتركة بين كذا سيستم (زي الإكسسوار والزجاج) تتعمل من غير `system_id`.

## 4) النموذج (الشباك أو الباب) بصورته وتخصيماته
```json
POST /api/v1/library/models
{"system_id": "...", "code": "SL2", "name": "شباك جرار ضلفتين", "category": "window",
 "status": "trial", "image_id": "<صورة تظهر في عرض السعر وأمر التصنيع>",
 "definition": {
   "params": [
     {"name": "leaf_count", "label": "عدد الضلف", "type": "int", "default": 2, "min": 2, "max": 4},
     {"name": "bar", "label": "البار", "type": "choice", "default": 38,
      "choices": [{"value": 0, "label": "بدون"}, {"value": 38, "label": "3.8 سم"}, {"value": 60, "label": "6 سم"}]},
     {"name": "with_screen", "label": "بسلك", "type": "bool", "default": true}
   ],
   "formulas": [
     {"key": "sash_w", "label": "عرض الضلفة", "expr": "(width + sash_overlap_total) / leaf_count"},
     {"key": "sash_h", "label": "ارتفاع الضلفة", "expr": "height - sash_height_deduction"},
     {"key": "area", "label": "المساحة", "expr": "width * height / 10000", "unit": "area_m2"}
   ],
   "pieces": [
     {"key": "frame_h", "label": "حلق أفقي", "role": "frame", "material_code": "KP-WG6",
      "length_expr": "width + 2 * weld_allowance", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
     {"key": "frame_v", "label": "حلق رأسي", "role": "frame", "material_code": "KP-WG6",
      "length_expr": "height + 2 * weld_allowance", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
     {"key": "sash_h_piece", "label": "ضلفة أفقي", "role": "sash", "material_code": "KP-WG7",
      "length_expr": "sash_w + 2 * weld_allowance", "qty_expr": "2 * leaf_count", "angle_left": "45", "angle_right": "45"},
     {"key": "steel", "label": "حديد تدعيم", "role": "reinforcement", "material_code": "KP-IR1",
      "length_expr": "width - 2", "qty_expr": "2", "condition": "width > 100"}
   ],
   "glass": [
     {"key": "pane", "label": "زجاج الضلفة", "width_expr": "sash_w - glass_deduction",
      "height_expr": "sash_h - glass_deduction", "qty_expr": "leaf_count"}
   ],
   "accessories": [
     {"key": "handle", "material_code": "ACC-HD11", "qty_expr": "1"},
     {"key": "locks", "material_code": "ACC-TSK-SKGS", "qty_expr": "2 * leaf_count"},
     {"key": "screen_wheels", "material_code": "ACC-NW-WLG", "qty_expr": "2", "condition": "with_screen"}
   ],
   "validations": [
     {"expr": "sash_w >= 30", "level": "error", "code": "SASH_TOO_NARROW", "message": "الضلفة أضيق من 30 سم"},
     {"expr": "height <= 250", "level": "warning", "code": "TALL", "message": "ارتفاع أكبر من المعتاد"}
   ],
   "drawing": [
     {"type": "frame", "x": "0", "y": "0", "w": "width", "h": "height"},
     {"type": "sash", "opening": "sliding_left", "x": "0", "y": "0", "w": "sash_w", "h": "sash_h"}
   ]
 }}
```

### الأسامي المتاحة في أي معادلة
| الاسم | المعنى |
|---|---|
| `opening_width`، `opening_height` | مقاس الفتحة من المعاينة (بوحدة السيستم) |
| `width`، `height` | مقاس التصنيع = الفتحة − خلوص التركيب (بيتحسب أوتوماتيك، والاتنين بيتسجلوا) |
| كل ثوابت السيستم | بالقيمة الفعلية = قيمة المكتبة (أو قيمة الشركة الخاصة) + معايرة الشركة |
| كل `params` | المتغيرات اللي المستخدم بيختارها |
| كل `formulas` | ممكن معادلة تستخدم معادلة تانية؛ الترتيب بيتحدد أوتوماتيك والحلقات بتترفض |

### المسموح في المعادلات
- `+ - * / %`، والأقواس، والمقارنات `< <= > >= == !=`، و`and or not`، و`true false`.
- الدوال: `min` و`max` و`abs` و`round(x)` و`round(x, n)` و`ceil` و`floor`، و`round_to(x, step)` و`ceil_to` و`floor_to` (للتقريب لخطوة)، و`clamp(x, lo, hi)`.
- `if(شرط, لو صح, لو غلط)`.
- `lookup(x, حد1, قيمة1, حد2, قيمة2, ..., القيمة الافتراضية)`: أول حد x أقل منه أو يساويه. ولو عايز أقل منه بس، استخدم `lookup_lt`. مثال مقاس بوكس الشاتر: `if(opening_height < 110, 16, lookup(opening_height, 135, 18, 190, 20, 270, 25, 0))`، ومعاه validation بيرفض الصفر (برّه النطاق).
- مفيش أي حاجة غير دي (ولا `eval` ولا وصول لأي حاجة في السيستم).

### القطع (`pieces`): التخصيم لكل خامة
- **كل عنصر (الحلق، الضلفة، الباكتة، السلك...) ليه تخصيم للعرض وتخصيم للارتفاع.** كل واحد منهم قطعة، وفيها `"element": "حلق"`
  و`"side": "width"` أو `"height"`. الواجهة بتعرضهم مع بعض في سطر واحد (العرض الأول وبعده الارتفاع)، وكشف التقطيع بيكتب جنب كل قطعة هي عرض ولا ارتفاع.
  مثال:
  `{"key": "frame_w", "element": "حلق", "side": "width", "length_expr": "width + 2 * weld_allowance", ...}` و
  `{"key": "frame_h", "element": "حلق", "side": "height", "length_expr": "height + 2 * weld_allowance", ...}`.
- `length_expr` هي معادلة طول القطعة (التخصيم)، و`qty_expr` عددها لكل شباك، و`angle_left` و`angle_right` زاوية التقطيع.
- `role` (frame / sash / mullion / bead / reinforcement / screen / track...) بيُستخدم في التحقق؛ مثلًا الضلفة مايصحش تبقى أطول من الحلق.
- `condition` اختياري: القطعة بتطلع بس لو الشرط صح.

### التحقق التلقائي (من غير ما تكتبه)
القطعة لازم تبقى موجبة، ومش أقصر من `min_piece_mm`، ومش أطول من العود. والعدد لازم يبقى رقم صحيح ومش سالب. والزجاج لازم يكون موجب ومش أكبر من الفتحة. والضلفة مش أطول من الحلق. ومقاس التصنيع بعد الخلوص لازم يفضل موجب.

## 5) اختبارات مرجعية لكل نموذج (إلزامية عمليًا)
لكل نموذج، سجّل مقاسات انت متأكد من نتيجتها في المصنع:
```json
POST /api/v1/library/models/{id}/tests
{"name": "100x100 ضلفتين", "opening_width_mm": "1000", "opening_height_mm": "1000", "params": {"leaf_count": 2},
 "expected": {"values": {"sash_w": "541"}, "pieces": {"frame_h": "1006"}, "piece_qty": {"sash_h_piece": 4},
              "glass": {"pane": ["411", "795"]}, "accessories": {"locks": 4}}}
```
النشر **بيترفض** لو أي اختبار اختلف بأكتر من 0.1 مم. وده بيحميك لو حد عدّل ثابت بالغلط.

## 6) جرّب، وبعدين انشر
- `POST /library/models/{id}/check`: أخطاء الصيغة والأسامي والحلقات والخامات.
- `POST /library/models/{id}/preview`: حساب تجريبي بالمسودة.
- `POST /library/models/{id}/tests/run`: تشغيل الاختبارات المرجعية.
- `POST /library/systems/{id}/publish {"notes": "..."}`: بيعمل **نسخة مجمّدة**. كل الحسابات بتستخدم آخر نسخة منشورة، وأي تعديل مش منشور مابيأثرش على العملاء. الأوامر القديمة محفوظ معاها رقم النسخة، فمابتتغيرش أبدًا.

## 7) الشركة (العميل) بعد كده
- **المعايرة:** `PUT /library/systems/{id}/adjustments` بالشكل `{"calibrations": [{"constant_name": "weld_allowance", "delta": "0.1"}]}`. ده بيزوّد 1 مم في اللحام عند الشركة دي بس، والمعادلة الأصلية مابتتغيرش.
- **قيمة خاصة لثابت:** `overrides`.
- **سعرها وكودها الداخلي لأي خامة:** `PUT /library/materials/{id}/settings`.
- كل ده متخزن منفصل عن المكتبة، **وتحديث المكتبة عمره ما يمسحه**.

## 8) توصيل المكتبة للعملاء الأوفلاين
1. على سيرفرك: `POST /library/packages/export {"system_codes": ["KOMBIN-SL"], "notes": "..."}` ← ملف zip غير موقّع.
2. على جهازك: `python -m tools.vendor_admin sign-package mytech-library-....unsigned.zip --key ~/.mytech/vendor_private.pem`.
3. عند العميل (مستخدم عنده `library.import`): `POST /library/packages/preview` (ارفع الملف) ← يظهر **كل اللي هيتغير**: سيستمات جديدة، ثوابت اتغيرت (القديم والجديد)، خامات ونماذج اتضافت أو اتغيرت أو اتشالت، ونسخ منشورة جديدة.
4. `POST /library/packages/{import_id}/apply` ← يتطبق.

السيستم بيتحقق من التوقيع ومن سلامة كل ملف. الـ IDs واحدة عند كل العملاء، والنسخ المنشورة عمرها ما بتتكتب فوقها. الخامات والنماذج اللي اتشالت بتتعطل بس (مابتتمسحش) عشان الأوامر القديمة. ومعايرة الشركة مابتتلمسش.
