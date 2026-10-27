# MYTech Solutions — API

- كل الـ endpoints تحت `/api/v1`. التوثيق التفاعلي (OpenAPI/Swagger) على `/api/docs`، والـ schema على `/api/openapi.json`.
- الـ API ماعندوش أي حاجة خاصة بالمتصفح (مفيش cookies ولا sessions)، فنفس الـ endpoints هتشتغل مع تطبيق موبايل بعدين من غير تعديل.
- **الأطوال دايمًا بالمليمتر** في الطلبات والردود. الأرقام العشرية والفلوس بترجع **نصوص** (`"1006.5"`) عشان الدقة متضيعش.
- التواريخ ISO-8601 بالـ timezone.

## القواعد العامة

### الدخول
```
POST /auth/login     {company_code?, username, password, device_key, device_name?, client_version?, platform?}
  -> {access_token, refresh_token, expires_in, user_id, company_id, must_change_password}
```
- `company_code` اختياري في الأوفلاين (فيه شركة واحدة)، ولازم في الأونلاين.
- `device_key`: معرّف ثابت للجهاز بيولّده العميل أول مرة ويحفظه. بيتعد ضمن حد الأجهزة في الترخيص.
- كل طلب بعد كده لازم يبعت الهيدر `Authorization: Bearer <access_token>`. التوكن صالح 15 دقيقة.
- `POST /auth/refresh {refresh_token}` بيرجّع توكنز جديدة. الـ refresh بيتغير كل مرة، ولو اتبعت refresh قديم تاني بتتلغي كل جلسة الجهاز ده (`TOKEN_REUSED`).
- `POST /auth/logout {refresh_token}` و`GET /auth/me` (الصلاحيات لكل فرع) و`POST /auth/change-password`.
- بعد 5 محاولات غلط الحساب بيتقفل 15 دقيقة (`423 ACCOUNT_LOCKED`).

### الإصدارات
- العميل يبعت `X-Client-Version: 1.2.0`، والسيرفر يرد بـ `X-Server-Version` و`X-Min-Client-Version`.
- لو العميل أقدم من المسموح: `426 CLIENT_UPDATE_REQUIRED`، والواجهة تعرض رسالة إن الجهاز محتاج يتحدث.
- `GET /system/info` من غير دخول بيرجّع اسم المنتج والإصدار والوضع، وبيُستخدم في اكتشاف السيرفر.

### الأخطاء
كلها بنفس الشكل:
```json
{"error": {"code": "VERSION_CONFLICT", "message": "...", "details": {...}}}
```
| HTTP | أكواد شائعة |
|---|---|
| 401 | `UNAUTHORIZED`، `TOKEN_EXPIRED`، `TOKEN_INVALID`، `TOKEN_REUSED`، `INVALID_CREDENTIALS` |
| 402 | `LICENSE_INVALID`، `LICENSE_READ_ONLY`، `LICENSE_DEVICE_LIMIT`، `LICENSE_USER_LIMIT`، `LICENSE_BRANCH_LIMIT`، `MODULE_NOT_LICENSED` |
| 403 | `PERMISSION_DENIED`، `LIBRARY_READ_ONLY`، `PLATFORM_ONLY` |
| 404 | `NOT_FOUND` (وده نفس الرد لما سجل يخص شركة تانية؛ السيستم مابيعترفش إنه موجود أصلًا) |
| 409 | `VERSION_CONFLICT`، `INVALID_TRANSITION`، `DEPOSIT_REQUIRED`، `INSUFFICIENT_STOCK`، `INSUFFICIENT_CASH`، `QUOTE_LOCKED`، `NOT_PUBLISHED` |
| 422 | `VALIDATION_FAILED`، `CALC_INVALID`، `PUBLISH_FAILED`، `UNKNOWN_MATERIAL`، `PACKAGE_SIGNATURE_INVALID` |
| 423 | `ACCOUNT_LOCKED` |
| 426 | `CLIENT_UPDATE_REQUIRED` |

### التعديل المتزامن (optimistic locking)
كل سجل بيرجع ومعاه `version`. أي `PATCH` لازم يبعت `version` اللي العميل قراه. لو حد تاني عدّل السجل في الوقت ده، الرد بيبقى `409 VERSION_CONFLICT`، والـ `details.current` فيها النسخة الحالية عشان الواجهة تعرض الفرق. مفيش تعديل بيمسح تعديل حد تاني.

### الصفحات
القوايم بتاخد `?limit=50&offset=0` (أقصى limit هو 500)، والرد بالشكل `{items, total, limit, offset}`.

### الصلاحيات
كل endpoint محتاج صلاحية معينة (`GET /permissions` بيرجّع القايمة كاملة). الصلاحية بتتمنح بالدور، والدور بيتربط بالفرع، فالمستخدم مابيشوفش ولا بيعدّل غير في الفروع اللي ليه فيها الصلاحية.

### الترخيص
- **الإضافة والحذف صلاحيات منفصلة** لكل قسم (`customers.create` / `customers.delete`، ...). كل `DELETE` بيرجّع `{"result": "deleted"}` أو `{"result": "deactivated"}` (للي ليه تاريخ)، أو `409` بسبب واضح (`QUOTE_IN_USE`، `WO_IN_USE`، `INVOICE_ISSUED`، `PO_NOT_DRAFT`). الفلوس عمرها ما بتتمسح: حركة الخزينة بتتعكس (`treasury.delete`) والفاتورة الصادرة بتتلغي (`invoices.delete`).
- لو الترخيص أو الاشتراك منتهي: فترة سماح، وبعدها السيستم بيبقى **قراءة بس** (`LICENSE_READ_ONLY` على أي POST/PUT/PATCH/DELETE).
- لو الترخيص مش موجود أو متلاعب فيه: مفيش أي وصول، ما عدا رفع ترخيص جديد.

### التحديث اللحظي
```
WS /api/v1/system/events?token=<access_token>
-> {"type": "change", "entity": "work_orders", "id": "...", "action": "update", "at": "..."}
-> {"type": "ping"}   (كل 25 ثانية)
```
أي تعديل بيوصل كل الأجهزة المتصلة من نفس الشركة، والحدث مافيهوش أي بيانات شخصية. العميل يعيد تحميل السجل بالـ API العادي، وده بيطبّق الصلاحيات. ولو الاتصال قطع، العميل يعيد الاتصال لوحده.

---

## الـ Endpoints

### system
| | | |
|---|---|---|
| GET | `/system/info` | (عام) المنتج، الإصدار، الوضع، أقل إصدار مسموح للأجهزة |
| GET | `/system/health` | (عام) فحص الداتابيز |
| GET | `/system/license` | حالة الترخيص والموديولات والحدود، وبصمة الجهاز في الأوفلاين |
| POST | `/system/license` | (أوفلاين، `system.manage`) رفع ملف ترخيص موقّع (multipart `file`) |
| GET / POST | `/system/backups` | قايمة النسخ الاحتياطية وآخر حالة / نسخة فورية (`system.manage`؛ في الأونلاين MYTech بس) |
| WS | `/system/events` | التحديث اللحظي |
| GET | `/system/branding?company_code=`، `/system/branding/logo?company_code=` | (عام) اسم الشركة ولوجوها ولونها، عشان شاشة الدخول. في الأوفلاين `company_code` اختياري |

### org: الشركة والفروع والمستخدمين
| | | |
|---|---|---|
| GET / PATCH | `/company` | بيانات الشركة وإعداداتها: العملة، الضريبة الافتراضية، نسبة العربون، صلاحية العرض، هالك التسعير، سلاح المنشار، تشذيب أطراف العود، أقل فُضلة تتشال، شروط العرض، `opening_capital` (رأس المال الأساسي: بيظهر بس لمين عنده `org.manage` أو `finance.read`) |
| | | `branding` جوه الرد: الاسم المعروض، التليفونات، الإيميل، الموقع، العنوان، الرقم الضريبي، السجل التجاري، تذييل الفاتورة، لون الشركة، `logo_media_id`، `length_unit` (`cm` افتراضي) |
| GET / POST | `/company/logo` | لوجو الشركة (multipart `file`، PNG/JPEG/WEBP). بيظهر في كل صفحات البرنامج والمطبوعات |
| GET / POST / PATCH | `/branches`، `/branches/{id}` | الفروع (مصنع / مخزن / معرض / مكتب) |
| GET | `/permissions` | كل الصلاحيات |
| GET / POST / PATCH | `/roles`، `/roles/{id}` | الأدوار. فيه أدوار جاهزة: مدير، مبيعات، إنتاج، مخازن، حسابات |
| GET / POST / GET / PATCH | `/users`، `/users/{id}` | المستخدمين و`assignments: [{role_id, branch_id or null}]` |
| GET / PATCH | `/devices`، `/devices/{id}` | الأجهزة المسجلة وإصدار كل جهاز، وتعطيل جهاز |
| GET | `/audit-log?entity=&entity_id=` | سجل التعديلات (القيم الشخصية متخفية `***`) |

### library: مكتبة القطاعات
القراءة بصلاحية `library.read`. التأليف بصلاحية `platform.library.author` لـ MYTech، أو `library.manage` للقطاعات الخاصة بالشركة.

| | | |
|---|---|---|
| POST | `/library/media` | رفع صورة PNG/JPEG/WEBP (حد أقصى 5MB). بيرجّع `{id, url}` |
| GET | `/media/{id}` | تحميل الصورة (لعرض السعر وأمر التصنيع) |
| GET / POST / PATCH | `/library/colors` | الألوان |
| GET / POST / GET / PATCH | `/library/systems` | سيستم القطاعات: `material_type` (upvc/shutter/aluminum)، و`unit` اللي المعادلات مكتوبة بيها (mm/cm)، والتقريب، والحالة (approved/trial). أي سيستم جديد بيتعمله أوتوماتيك ثابتين خلوص التركيب |
| GET / POST | `/library/systems/{id}/constants` | الثوابت بأساميها |
| PATCH / DELETE | `/library/constants/{id}` | |
| GET / POST / GET / PATCH | `/library/materials` | الخامات: الكود، النوع، الوحدة، طول العود، أقل قطعة، الوزن، السعر المرجعي، الصورة، و`variants` (لون ← SKU) |
| PUT | `/library/materials/{id}/settings` | سعر الشركة وكودها الداخلي وإخفاء الخامة (بيتخزن منفصل عن المكتبة) |
| GET / POST / GET / PATCH | `/library/models` | نماذج الشبابيك والأبواب بصورها وتعريفها الكامل (شوف `docs/LIBRARY.md`) |
| POST | `/library/models/{id}/check` | فحص التعريف: الأسامي، الحلقات، الخامات، صيغة المعادلات |
| POST | `/library/models/{id}/preview` | حساب بالمسودة قبل النشر |
| GET / POST | `/library/models/{id}/tests` | الاختبارات المرجعية للنموذج |
| DELETE | `/library/tests/{id}` | |
| POST | `/library/models/{id}/tests/run` | تشغيل الاختبارات المرجعية |
| DELETE | `/library/systems/{id}`، `/library/materials/{id}`، `/library/models/{id}` | لو عمره ما اتنشر ولا اتستخدم بيتمسح (السيستم بكل اللي جواه)، ولو اتنشر أو مستخدم بيتوقف بس (`{"result": "deactivated"}`). الخامة المستخدمة في نموذج: `MATERIAL_IN_USE` بأكواد النماذج. الشركة محتاجة `library.manage` + `library.delete` لصفوفها الخاصة بس |
| POST | `/library/systems/{id}/publish` | نشر نسخة مجمّدة. بيترفض لو أي نموذج فيه غلط أو أي اختبار مرجعي اختلف أكتر من 0.1 مم |
| GET | `/library/systems/{id}/versions`، `/library/versions/{id}` | النسخ المنشورة ومحتواها |
| GET / PUT | `/library/systems/{id}/adjustments` | معايرة الشركة (`calibrations: [{constant_name, delta}]`) وقيمها الخاصة (`overrides`) |
| POST | `/engine/calculate` | `{model_id, opening_width_mm, opening_height_mm, params, version_id?}` ← القطع (طول، عدد، زوايا)، الزجاج، الإكسسوار، الرسمة، التحذيرات، و`meta.formula_set_version_id` |
| POST | `/library/packages/export` | (MYTech) حزمة المكتبة، غير موقّعة |
| POST | `/library/packages/preview` | (`library.import`) رفع حزمة موقّعة ← بيرجّع كل اللي هيتغير من غير ما يطبّق حاجة |
| POST | `/library/packages/{import_id}/apply` | تطبيق الحزمة |
| GET | `/library/packages/imports` | سجل الحزم اللي اتستوردت |

### crm: العملاء والمعاينات
| | | |
|---|---|---|
| GET / POST / GET / PATCH | `/customers` | العملاء (end/dealer/contractor). أي عرض أو تعديل للبيانات الشخصية بيتسجل |
| GET / POST / GET / PATCH | `/surveys` | المعاينات (`kind`: `window` شبابيك وأبواب أو `shutter` شيش، و`floor` الدور، و`technician` الفني) و`openings`: مقاس الفتحة كما اتقاس، و`total_height_mm` الارتفاع الكلي، والنموذج (رقم الوحدة) ومتغيراته، واللون (`color_code` من المكتبة أو `color_text` زي ما اتكتب)، و`unit_kind` (`sliding` جرار / `hinged` مفصلي)، و`glass_layers` (`single` / `double`) و`glass_color`، و`screen_type` السلك (`sliding` / `pleated` بليسيه / `hinged` ض.ض / `fixed`)، و`location` نوع الغرفة أو مكان الوحدة، و`application` التطبيق؛ وللشيش `installation_method` و`motor_type` |
| GET | `/surveys/{id}/pricing` | دليل المبيعات للمعاينة: `cost_total` (تكلفة العملية = الخامات بالتخصيمات + `labor_cost_per_m2` × المساحة)، و`fair_total` (السعر العادل = التكلفة + `fair_margin_pct`، افتراضي 20%) و`top_total` (التكلفة + `top_margin_pct`، افتراضي 30%)، وسعر المتر لكل واحد = الإجمالي ÷ المساحة المحسوبة، و`missing_costs` (خامات من غير سعر). المساحة = العرض × الارتفاع الكلي لو مكتوب، وإلا العرض × الارتفاع، وأي وحدة أقل من `min_billed_area_m2` (افتراضي 1 م²) بتتحسب بيه |
| GET | `/surveys/{id}/print` | ورقة المعاينة (A4 بالعرض) بنفس أعمدة الورقة، وأقل حاجة 10 صفوف عشان المعاينة الفاضية تتطبع فورمة للفني |

### sales: عروض الأسعار
موظف المبيعات بيكتب السعر بإيده. السيستم بيدّيله دليل: السعر العادل (التكلفة + 20%) وأعلى سعر (التكلفة + 30%)، والنسب في إعدادات الشركة.
لو الإجمالي بعد الخصم أقل من `fair_total` لازم مدير المبيعات (`quotes.approve_price`) يوافق قبل ما العرض يتبعت أو يتقبل.
قوائم الأسعار اتشالت (الجداول فاضلة عشان العروض القديمة، وأسعار سطورها القديمة بتفضل زي ما هي حتى لو اتعمل إعادة حساب).
| | | |
|---|---|---|
| GET / POST / GET / PATCH | `/quotations` | لو بعت `survey_id` من غير سطور، العرض بيتعمل أوتوماتيك من المعاينة. كل سطر بيتحسب ويتسعّر |
| POST | `/quotations/{id}/lines` | إضافة سطر. `price_per_m2` (سعر المتر اللي بيكتبه المستخدم) ليه الأولوية: سعر الوحدة = `billed_area_m2` (المساحة بحد أدنى؛ العرض × `total_height_mm` لو مكتوب) × سعر المتر؛ وبعده `manual_unit_price`. لو مفيش سعر مكتوب السطر بيفضل `priced=false` وسعره صفر. كل سطر بيرجّع `fair_unit_price` و`top_unit_price` و`fair_price_per_m2` و`top_price_per_m2` و`model_code`. العرض بيرجّع `fair_total` و`top_total` و`net_total` و`needs_price_approval` و`unpriced_lines` |
| | أرج | لو `total_height_mm` أكبر من `opening_height_mm`: فيه أرج نص دايرة فوق الوحدة، وحدة لوحدها بحلقها. بيتحسب بنموذج `top_model_id` (أو `default_arch_model_id` في إعدادات الشركة)، عرضه عرض الوحدة وارتفاعه = الكلي − الارتفاع. بيطلع سطر تابع (`parent_line_id`) سعره صفر، لأن تكلفته داخلة في الوحدة. بيتعدل ويتمسح مع وحدته بس (`ARCH_LINE_MANAGED`)، وبيتنقل لأمر التصنيع كوحدة. لو مفيش نموذج أرج: `ARCH_MODEL_REQUIRED` |
| POST | `/quotations/{id}/price-per-m2` | سعر متر واحد لكل السطور (`null` = يرجع لسعر كل سطر) |
| PATCH / DELETE | `/quotation-lines/{id}` | |
| POST | `/quotations/{id}/status` | draft ← sent ← accepted/rejected/expired. لـ sent وaccepted: `QUOTE_UNPRICED` لو فيه سطر من غير سعر، و`PRICE_APPROVAL_REQUIRED` لو تحت السعر العادل من غير موافقة |
| POST | `/quotations/{id}/request-price-approval` | الموظف بيطلب الموافقة: إشعار لمديري المبيعات في الفرع |
| POST | `/quotations/{id}/approve-price` | مدير المبيعات بيوافق على الإجمالي الحالي (`version`, `note`). لو الإجمالي نزل تاني تحت اللي اتوافق عليه بيحتاج موافقة جديدة |
| POST | `/quotations/{id}/recalculate` | إعادة الحساب بالمعادلات والأسعار الحالية (لازم تتطلب صراحةً) |

### production: أوامر التصنيع
| | | |
|---|---|---|
| GET / POST | `/work-orders` | أمر بيبدأ من مرحلة المعاينة |
| POST | `/work-orders/from-quotation` | من عرض سعر متوافق عليه (السطور بتتنسخ وتتجمّد) |
| GET / PATCH | `/work-orders/{id}` | الملاحظات، ميعاد التسليم، العربون المطلوب، البائع (`salesperson_id`) |
| POST | `/work-orders/{id}/stage` | `{version, to}`: خطوة لقدام بس أو `cancelled`. للموافقة لازم العربون يكون اتدفع. دخول مرحلة التصنيع بيجمّد مخرجات التصنيع |
| GET | `/work-orders/{id}/manufacturing` | كشف التقطيع لكل SKU، خطة الأعواد ونسبة الهالك، الزجاج، الإكسسوار، التكلفة الفعلية، بيانات الرسمة وصورة النموذج |
| POST | `/work-orders/{id}/manufacturing/generate` | إعادة توليد المخرجات (قبل التصنيع بس) |

مفيش مخازن (اتشالت بطلب صاحب المشروع، migration 0011): البضاعة بتتطلب لكل أمر من «طلبية بضاعة».
كل بيعة ليها بائع: `salesperson_id` (موظف) على عرض السعر، وبيتنقل لأمر التصنيع والفاتورة. لو ماتبعتش، بيتاخد الموظف المربوط بحساب اللي عامل البيعة.

### purchasing: الموردين والمشتريات
| | | |
|---|---|---|
| GET / POST / PATCH | `/suppliers` | |
| GET / POST | `/purchase-orders` | |
| POST | `/purchase-orders/{id}/approve` | `{version, approve, note}`: الحسابات بتأكد (`approved`) أو ترفض (`rejected`) أمر الشراء. صلاحية `purchasing.approve` |
| POST | `/purchase-orders/{id}/status` | ordered (بعد تأكيد الحسابات بس، وإلا `PO_NOT_APPROVED`) / cancelled |
| POST | `/purchase-orders/{id}/receive` | استلام جزئي أو كامل من المورد (بيدخل في مشتريات الربحية). آخر سعر شراء بيبقى سعر الشركة |

### treasury: الخزينة
| | | |
|---|---|---|
| GET / POST | `/cashboxes` | خزينة لكل فرع ورصيدها |
| GET / POST | `/cash-transactions` | قبض أو صرف (`in`/`out`)، مربوط بعميل وأمر تصنيع أو بمورد وأمر شراء |
| POST | `/cash-transactions/{id}/reverse` | عكس الحركة (الحركات مابتتعدلش) |
| GET | `/customers/{id}/statement`، `/suppliers/{id}/statement` | كشف حساب |


### استيراد الخامات من إكسيل
| | | |
|---|---|---|
| POST | `/library/import-excel?apply=false` | ملف `.xlsx`: معاينة اللي هيتضاف ويتحدث وأخطاء كل سطر (مفيش حاجة بتتحفظ) |
| POST | `/library/import-excel?apply=true` | الاستيراد: كله أو مفيش (`IMPORT_ERRORS` بتفاصيل كل سطر) |
| GET | `/library/import-excel/template` | قالب فاضي بالشيتات والأعمدة |

الأعمدة: السيستم، الكود، الاسم، النوع (قطاع، حديد تدعيم، إكسسوار، كاوتش، مستهلكات، بانل، زجاج، أخرى)، الوحدة (متر، قطعة، طقم، لفة، م²، كجم، عود)، طول العود (مم)، المجموعة، اللون (اسمه من شيت الألوان)، كود الصنف (SKU)، سعر المورد، السعر على، ملاحظات، وزن المتر (كجم)، خصم المورد %.
سعر العود بيتحول لسعر المتر، وسعر الكيلو لقطاع ليه وزن متر بيتحول لسعر المتر. خصم المورد كمان بيتحط لكل نوع قطاع من بيانات الشركة (`supplier_discounts`).

### البواقي
| | | |
|---|---|---|
| GET / POST | `/offcuts?status=available&sku=` | الفُضل (من «أقل فُضلة تتشال»، افتراضي 400 مم) لكل قطاع بلونه وطوله. الإضافة لفُضلة موجودة في المصنع |
| POST | `/offcuts/{id}/scrap` | اتشال هالك |

البواقي بتتعمل أوتوماتيك لما الأمر يدخل تصنيع، والأمر بيقطع من البواقي الموجودة الأول (`offcuts_used` في خطة الأعواد و`material-needs`).

### الإشعارات وتأكيد البيعة
| | | |
|---|---|---|
| GET | `/notifications?after=` | إشعاراتي (آخر 30، أو الجديد بعد وقت) وعدد اللي ماتقرأش. البرنامج بيسأل كل 15 ثانية |
| POST | `/notifications/{id}/read`، `/notifications/read-all` | |
| POST | `/work-orders/{id}/approve-sale` | `{version, approve, note}`: الحسابات بتأكد البيعة أو ترفضها (`sales.approve`). من غيرها الأمر مايتنقلش لـ approved (`SALE_NOT_APPROVED`) |
| GET | `/work-orders?sale_status=pending` | المبيعات المستنية تأكيد |

مين يوصله إيه: صلاحية لكل قسم (`notify.accounts`، `notify.sales`، `notify.production`، `notify.field`) في الفرع. اللي عمل التغيير مابيوصلوش إشعار عن نفسه.

### hr: الموارد البشرية
| | | |
|---|---|---|
| GET / POST / PATCH / DELETE | `/employees`، `/employees/{id}` | الموظف: الوظيفة، القسم (`sales`، `production`، `installation`، ...)، الفرع، المرتب، الرقم القومي، رصيد الإجازات، وحسابه على البرنامج (`user_id`). قراءة بياناته الشخصية بتتسجل. اللي ليه مرتبات أو مبيعات بيتعلم إنه ساب الشغل بدل ما يتمسح |
| GET | `/employees/brief` | الأسماء بس (لاختيار البائع) لمين يشوف عروض الأسعار |
| GET | `/employees/{id}/summary`، `/sales`، `/payslips`، `/entries`، `/leaves` | باقي الإجازات والسلف، مبيعاته في السنة، مرتباته، حركاته، إجازاته |
| POST / DELETE | `/employee-entries` | `bonus` حافز / `deduction` خصم على مرتب شهر، أو `advance` سلفة بتتصرف من خزينة (`cashbox_id`) وتتخصم على أقساط (`installment`). السلفة بتتلغي بعكس حركة صرفها |
| POST / PATCH / DELETE | `/employee-leaves` | إجازة (اعتيادي، مرضي، من غير مرتب، أخرى). اللي من غير مرتب بتتخصم: المرتب ÷ 30 × الأيام |
| GET / POST | `/payroll-runs` | كشف مرتبات شهر لفرع: لكل موظف الأساسي + الحوافز − الخصومات − الإجازات من غير مرتب = التكلفة، وناقص قسط السلفة = الصافي |
| POST | `/payroll-runs/{id}/recalculate`، `/pay` | إعادة الحساب، والصرف من خزينة (حركة باسم كل موظف؛ الكشف بيتقفل ومابيتعكسش) |

### finance: الأصول والربحية ورأس المال
| | | |
|---|---|---|
| GET / POST / PATCH / DELETE | `/assets` | أصول الشركة بقيمتها (من غير إهلاك). المباع أو المتشال بيبقى `disposed` |
| GET | `/finance/profit?year=` | لكل شهر: المبيعات (الفواتير الصادرة من غير ضريبة) − المشتريات (المستلم) − المرتبات (الكشوف المصروفة) − المصروفات (صرف الخزينة لطرف «أخرى») |
| GET | `/finance/capital` | رأس المال الأساسي + الأصول الموجودة + الأرباح المتراكمة |

### invoicing: فواتير العملاء
صلاحية `treasury.write` للتعديل و`treasury.read` للقراءة.
| | | |
|---|---|---|
| GET / POST | `/invoices` | الفواتير. الإنشاء من `work_order_id` أو `quotation_id` (السطور بتتنسخ بالموديل وصورته ورسمته والمقاسات واللون والزجاج والسعر)، أو سطور يدوي `lines` |
| GET / PATCH | `/invoices/{id}` | الفاتورة بسطورها والمدفوع والباقي. التعديل في المسودة بس: خصم، ضريبة، تاريخ استحقاق، ملاحظات، شروط |
| POST | `/invoices/{id}/lines`، PATCH / DELETE `/invoice-lines/{id}` | سطور المسودة (صنف أو خدمة، كمية، سعر، خصم %) |
| POST | `/invoices/{id}/issue` | إصدار: رقم متسلسل من غير فراغات (`INV-…`) والفاتورة بتتقفل |
| POST | `/invoices/{id}/cancel` | `{reason}` إلغاء (مابتتمسحش) |

القبض على فاتورة: `POST /cash-transactions` بـ `invoice_id` (لازم تكون صادرة ونفس العميل).

### field: الصيانة والفنيين والتتبع
| | | |
|---|---|---|
| GET / POST / GET / PATCH / DELETE | `/maintenance` | طلبات الصيانة (`customer_id`، المشكلة، العنوان، `location_url`، الحالة open/scheduled/done/cancelled، التكلفة) |
| GET / POST / PATCH / DELETE | `/field/jobs` | مهام الفنيين: `kind` (survey/installation/maintenance)، `technician_id`، `scheduled_at`، ومربوطة بمعاينة أو أمر أو طلب صيانة. `?mine=true` للفني |
| POST | `/field/jobs/{id}/status` | `on_way` ← `arrived` ← `done` (الفني أو المكتب)، `cancelled` (المكتب بس) |
| POST | `/field/locations` | نقطة GPS من موبايل الفني؛ بتترفض (`NO_ACTIVE_JOB`) لو مفيش مهمة شغالة |
| GET | `/field/technicians`، `/field/jobs/{id}/track`، `/field/technician-users` | آخر مكان لكل فني ومهمته الحالية، مسار مهمة، أسماء الفنيين. قراءة المكان بتتسجل في سجل البيانات الشخصية |
| GET | `/tech` | تطبيق الفني (صفحة موبايل قابلة للتسطيب) |

اللوكيشن في المعاينة وطلب الصيانة والمهمة: `location_url` (لينك جوجل ماب)، والسيرفر بيطلّع منه `latitude`/`longitude`.
أوامر التصنيع فيها `progress_pct` و`expected_delivery` و`late` من مدة كل مرحلة (`stage_durations_days` في إعدادات الشركة).
`GET /work-orders/{id}/material-needs`: القطاعات (أعواد كاملة بعد تحسين التقطيع) والزجاج والإكسسوار، ومنها أمر شراء بـ `work_order_id` (بيتربط بالعميل).

### documents: المطبوعات (A4 HTML جاهز للطباعة أو حفظ PDF)
كل مطبوع فيه اسم الشركة ولوجوها وبياناتها، والمقاسات بالسنتيمتر والعرض قبل الارتفاع، والصور والخطوط جوه الملف (من غير إنترنت).
| | | |
|---|---|---|
| GET | `/invoices/{id}/print` | الفاتورة: شكل النموذج ورسمته، المقاس، اللون، الزجاج، الكمية، السعر، الخصم، الضريبة، المدفوع والباقي |
| GET | `/quotations/{id}/print` | عرض السعر بنفس التفاصيل والعربون المطلوب |
| POST | `/documents/report` | طباعة أي شاشة: البرنامج بيبعت عنوان الصفحة وجداولها وبياناتها كنص (`sections`: `columns`/`rows`/`kv`)، والسيرفر بيرجّع A4 بلوجو الشركة وبياناتها (بالعرض لو الأعمدة أكتر من 7). مسموح حتى والترخيص قراءة بس |
| GET | `/work-orders/{id}/print/cut-list` | كشف التقطيع: القطع لكل خامة (العنصر، عرض/ارتفاع، الطول، العدد، الزوايا) وخطة الأعواد والزجاج والإكسسوار |

### privacy: البيانات الشخصية
| | | |
|---|---|---|
| GET | `/privacy/subjects/{customer|user|supplier}/{id}/export` | كل البيانات عن الشخص |
| POST | `/privacy/subjects/{type}/{id}/erase` | `{reason}`: إخفاء الهوية مع الإبقاء على السجلات المالية |
| GET | `/privacy/access-log?subject_id=&user_id=` | مين شاف أو عدّل أو صدّر أو مسح، وإمتى |

---

## برنامج الديسكتوب: إزاي يتعامل مع السيرفر
الواجهة **برنامج ديسكتوب** (قرار صاحب المشروع). المطلوب من البرنامج:

1. **إيجاد السيرفر (أوفلاين):**
   - يبعت UDP broadcast بالنص `MYTECH_DISCOVER` على بورت `47800`.
   - كل سيرفر بيرد بـ JSON: `{"product", "version", "host", "address", "port", "scheme", "api"}`.
   - بديل: يدوّر على خدمة mDNS `_mytech._tcp.local.`.
   - لو مالقاش حاجة، يطلب من المستخدم يكتب العنوان يدوي.
   - يحفظ آخر عنوان شغال ويجرّبه الأول المرة الجاية.
   - المرجع: `backend/app/ops/discovery.py` (الدالة `discover()`) و`tools/find_server.py`.
   - في الأونلاين: العنوان ثابت (https).
2. **هوية الجهاز:** أول تشغيل يولّد `device_key` عشوائي (UUID) ويحفظه، ويبعته مع كل `login` ومعاه `device_name` و`platform` و`client_version`.
3. **التوكنز:**
   - يحفظ الـ refresh token بشكل آمن (Windows Credential Manager / DPAPI).
   - لما ييجي `401 TOKEN_EXPIRED`، يعمل `refresh` ويعيد الطلب مرة واحدة.
   - لو جه `TOKEN_REUSED` أو `TOKEN_INVALID` أو `USER_DISABLED`، يرجّع شاشة الدخول.
4. **الإصدار:**
   - يبعت `X-Client-Version` مع كل طلب.
   - لو جه `426 CLIENT_UPDATE_REQUIRED`، يعرض إن البرنامج محتاج يتحدث (`details.min_client_version`).
5. **التحديث اللحظي:**
   - يفتح `WS /api/v1/system/events?token=...` بعد الدخول، ولما ييجي `change` يعيد تحميل الشاشة المفتوحة لو بتعرض نفس الـ `entity`/`id`.
   - يتجاهل `ping`.
6. **انقطاع الشبكة:**
   - يعرض حالة "غير متصل" ويعيد المحاولة لوحده (backoff: 1، 2، 5، 10 ثواني...).
   - مايخزّنش عمليات محليًا ولا يزامن بعدين (offline sync ممنوع).
   - لما الاتصال يرجع، يجدد التوكن ويفتح الـ WebSocket تاني.
7. **التعديل المتزامن:** يبعت `version` مع كل `PATCH`. لو جه `409 VERSION_CONFLICT` يعرض للمستخدم `details.current` ويخيّره (يحمّل الجديد أو يعيد تعديله).
8. **الصور:** `GET /media/{id}` بنفس التوكن، ويعمل لها cache محلي بالـ id (الصورة بالـ id مابتتغيرش).
