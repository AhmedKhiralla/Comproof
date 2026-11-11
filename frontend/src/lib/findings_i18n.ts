// Display-time translation of engine-written finding text (titles, explanations, actions, notes).
// The signed result stays in English; what the reviewer reads follows the interface language.
// Quoted packaging text and OCR readings (inside “ ”) are captured and shown exactly as printed.
import type { Lang } from "./i18n";

type Rule = { re: RegExp; fr: string; ar: string };

// $1…$9 are capture groups from the English text.
const RULES: Rule[] = [
  // ---- Level 2/3 titles (the part before “ — section” is replaced, the section tail stays)
  { re: /^Missing from design/, fr: "Manquant sur la maquette", ar: "ناقص في التصميم" },
  { re: /^Added in design/, fr: "Ajouté sur la maquette", ar: "مُضاف في التصميم" },
  { re: /^Number changed/, fr: "Nombre modifié", ar: "تغيّر في رقم" },
  { re: /^Wording changed/, fr: "Formulation modifiée", ar: "تغيّرت الصياغة" },
  { re: /^Text differs$/, fr: "Le texte diffère", ar: "النص مختلف" },
  { re: /^Numbers differ \(dose \/ strength \/ value\)$/, fr: "Les nombres diffèrent (dose / dosage / valeur)", ar: "الأرقام مختلفة (جرعة / تركيز / قيمة)" },
  { re: /^Text in approved leaflet is missing from design$/, fr: "Texte du document approuvé absent de la maquette", ar: "نص موجود في المعتمد وغائب عن التصميم" },
  { re: /^Text in design is not in approved leaflet$/, fr: "Texte de la maquette absent du document approuvé", ar: "نص في التصميم غير موجود في المعتمد" },
  { re: /^Probable OCR misread \(look-alike characters\)$/, fr: "Erreur de lecture OCR probable (caractères semblables)", ar: "خطأ قراءة OCR محتمل (حروف متشابهة)" },
  { re: /^Word spacing differs$/, fr: "L'espacement des mots diffère", ar: "تباعد الكلمات مختلف" },
  { re: /^Punctuation differs$/, fr: "La ponctuation diffère", ar: "علامات الترقيم مختلفة" },
  { re: /^Capitalisation differs$/, fr: "Les majuscules diffèrent", ar: "حالة الأحرف مختلفة" },
  { re: /^Digit style differs \(Western vs Arabic-Indic\)$/, fr: "Style des chiffres différent (occidentaux vs arabes)", ar: "نمط الأرقام مختلف (غربية مقابل هندية-عربية)" },

  // ---- Level 1 (master audit) titles and notes
  { re: /^Strength in name does not match quantity in composition$/, fr: "Le dosage du nom ne correspond pas à la quantité de la composition", ar: "التركيز في الاسم لا يطابق الكمية في التركيب" },
  { re: /^Dosage form wording: '(.+)' used for a (\w+) product$/, fr: "Forme pharmaceutique : « $1 » employé pour un produit de type « $2 »", ar: "صياغة الشكل الصيدلاني: استُخدم «$1» لمنتج من نوع «$2»" },
  { re: /^Heading appears twice$/, fr: "Titre répété deux fois", ar: "عنوان مكرر مرتين" },
  { re: /^ATC code '(.+)' is not a complete 7-character code$/, fr: "Le code ATC « $1 » n'est pas un code complet de 7 caractères", ar: "كود ATC «$1» ليس كودًا كاملًا من 7 خانات" },
  { re: /^SmPC section headings not found \(check numbering\)$/, fr: "Titres de rubriques du RCP introuvables (vérifier la numérotation)", ar: "عناوين أقسام RCP غير موجودة (راجع الترقيم)" },
  { re: /^Maximum dose stated with different values$/, fr: "Dose maximale indiquée avec des valeurs différentes", ar: "الجرعة القصوى مذكورة بقيم مختلفة" },
  { re: /^Missing space: '(.+)'$/, fr: "Espace manquante : « $1 »", ar: "مسافة ناقصة: «$1»" },
  { re: /Name says ([\d.,]+) mg, composition says ([\d.,]+) mg\./, fr: "Le nom indique $1 mg, la composition $2 mg.", ar: "الاسم يذكر $1 مجم بينما التركيب يذكر $2 مجم." },
  { re: /May also be an OCR miss — confirm on the scan\./, fr: "Peut aussi être une lecture OCR manquée — à confirmer sur la numérisation.", ar: "قد يكون أيضًا خطأ قراءة OCR — تأكد من النسخة الممسوحة." },

  // ---- Level 2/3 explanations
  { re: /The approved leaflet has (“[^”]*”) here; the design leaves it out\./, fr: "Le document approuvé contient $1 ici ; la maquette l'omet.", ar: "المستند المعتمد يحتوي على $1 هنا؛ والتصميم أغفله." },
  { re: /The design adds (“[^”]*”), which is not in the approved leaflet\./, fr: "La maquette ajoute $1, qui n'est pas dans le document approuvé.", ar: "التصميم يضيف $1 وهو غير موجود في المستند المعتمد." },
  { re: /Approved reads (“[^”]*”), design reads (“[^”]*”)\. Numbers: approved (.*?) → design (.*?)\./, fr: "L'approuvé se lit $1, la maquette $2. Nombres : approuvé $3 → maquette $4.", ar: "المعتمد يُقرأ $1 والتصميم $2. الأرقام: المعتمد $3 ← التصميم $4." },
  { re: /The two readings differ only by look-alike characters \(l\/1, O\/0, S\/5\); most likely the same text\./, fr: "Les deux lectures ne diffèrent que par des caractères semblables (l/1, O/0, S/5) ; très probablement le même texte.", ar: "القراءتان لا تختلفان إلا في حروف متشابهة (l/1، O/0، S/5)؛ على الأرجح النص نفسه." },
  { re: /Approved reads (“[^”]*”); the design reads (“[^”]*”)\./, fr: "L'approuvé se lit $1 ; la maquette se lit $2.", ar: "المعتمد يُقرأ $1؛ والتصميم يُقرأ $2." },
  { re: /Same letters, different word breaks: approved (“[^”]*”), design (“[^”]*”)\./, fr: "Mêmes lettres, découpage des mots différent : approuvé $1, maquette $2.", ar: "الحروف نفسها مع فواصل كلمات مختلفة: المعتمد $1 والتصميم $2." },
  { re: /Approved (“[^”]*”), design (“[^”]*”)\. The letters read almost the same, but the word breaks differ\./, fr: "Approuvé $1, maquette $2. Les lettres se lisent presque pareil, mais le découpage des mots diffère.", ar: "المعتمد $1 والتصميم $2. الحروف متقاربة جدًا لكن فواصل الكلمات مختلفة." },
  { re: /Approved (“[^”]*”), design (“[^”]*”)\. The letters read almost the same, but the punctuation differ\./, fr: "Approuvé $1, maquette $2. Les lettres se lisent presque pareil, mais la ponctuation diffère.", ar: "المعتمد $1 والتصميم $2. الحروف متقاربة جدًا لكن الترقيم مختلف." },
  { re: /Same text, different spacing: approved (“[^”]*”), design (“[^”]*”)\./, fr: "Même texte, espacement différent : approuvé $1, maquette $2.", ar: "النص نفسه بتباعد مختلف: المعتمد $1 والتصميم $2." },
  { re: /Same number, written in a different digit system\./, fr: "Même nombre, écrit dans un autre système de chiffres.", ar: "الرقم نفسه مكتوب بنظام أرقام مختلف." },
  { re: /Punctuation differs: approved (“[^”]*”), design (“[^”]*”)\./, fr: "La ponctuation diffère : approuvé $1, maquette $2.", ar: "الترقيم مختلف: المعتمد $1 والتصميم $2." },
  { re: /Capitalisation differs: approved (“[^”]*”), design (“[^”]*”)\./, fr: "Les majuscules diffèrent : approuvé $1, maquette $2.", ar: "حالة الأحرف مختلفة: المعتمد $1 والتصميم $2." },

  // ---- Category impact sentences (appended to Level 2 explanations)
  { re: /Wrong strength or composition is a product-identity error and a recall risk\./, fr: "Un dosage ou une composition erronés sont une erreur d'identité du produit et un risque de rappel.", ar: "خطأ التركيز أو التركيب خطأ في هوية المنتج وخطر استدعاء." },
  { re: /Dosing and administration text directly guides how patients take the medicine\./, fr: "Le texte de posologie et d'administration guide directement la prise du médicament par le patient.", ar: "نص الجرعات وطريقة الاستخدام يوجّه المريض مباشرة في تناول الدواء." },
  { re: /Safety text protects patients; any change needs regulatory approval\./, fr: "Le texte de sécurité protège les patients ; tout changement exige une approbation réglementaire.", ar: "نص السلامة يحمي المرضى؛ وأي تغيير يتطلب موافقة تنظيمية." },
  { re: /Scientific data must match the approved SmPC\./, fr: "Les données scientifiques doivent correspondre au RCP approuvé.", ar: "البيانات العلمية يجب أن تطابق ملخص خصائص المنتج المعتمد." },
  { re: /Storage and pack details affect product quality and traceability\./, fr: "Les mentions de conservation et d'emballage touchent la qualité et la traçabilité du produit.", ar: "بيانات التخزين والعبوة تمس جودة المنتج وتتبّعه." },
  { re: /Approved wording must be reproduced exactly on the printed leaflet\./, fr: "La formulation approuvée doit être reproduite à l'identique sur l'imprimé.", ar: "يجب نقل الصياغة المعتمدة حرفيًا على المطبوع." },

  // ---- Level 1 explanations
  { re: /The approved leaflet contradicts itself; the design team cannot know which is right\./, fr: "Le document approuvé se contredit ; le studio ne peut pas savoir quelle valeur est la bonne.", ar: "المستند المعتمد يناقض نفسه؛ ولا يمكن لفريق التصميم معرفة الصحيح." },
  { re: /Reference data in the approved leaflet looks incomplete or malformed\./, fr: "Une donnée de référence du document approuvé semble incomplète ou mal formée.", ar: "بيانات مرجعية في المستند المعتمد تبدو ناقصة أو غير سليمة." },
  { re: /The approved leaflet's structure has a defect\./, fr: "La structure du document approuvé présente un défaut.", ar: "بنية المستند المعتمد بها خلل." },
  { re: /A typo in the master will be copied into every artwork made from it\./, fr: "Une coquille dans la référence sera copiée dans chaque maquette qui en découle.", ar: "الخطأ المطبعي في المرجع سيُنسخ إلى كل تصميم مبني عليه." },

  // ---- Actions
  { re: /Correct the value on the artwork to match the approved leaflet, or raise a change control if the approved text itself is wrong\. Numbers must never differ\./, fr: "Corrigez la valeur sur la maquette pour correspondre au document approuvé, ou ouvrez une maîtrise des changements si le texte approuvé lui-même est erroné. Les nombres ne doivent jamais différer.", ar: "صحّح القيمة على التصميم لتطابق المستند المعتمد، أو افتح إجراء ضبط تغيير إذا كان النص المعتمد نفسه خاطئًا. الأرقام لا يجوز أن تختلف أبدًا." },
  { re: /Restore the missing text on the artwork exactly as approved\./, fr: "Rétablissez le texte manquant sur la maquette, exactement tel qu'approuvé.", ar: "أعد النص الناقص إلى التصميم كما اعتُمد تمامًا." },
  { re: /Remove the extra text, or get it approved through change control before printing\./, fr: "Retirez le texte ajouté, ou faites-le approuver par maîtrise des changements avant impression.", ar: "احذف النص الزائد أو اعتمده عبر ضبط التغيير قبل الطباعة." },
  { re: /Align the wording on the artwork with the approved leaflet\./, fr: "Alignez la formulation de la maquette sur le document approuvé.", ar: "طابق صياغة التصميم مع المستند المعتمد." },
  { re: /Check against the approved leaflet\./, fr: "Vérifiez par rapport au document approuvé.", ar: "تحقق بالمقارنة مع المستند المعتمد." },
  { re: /Fix the spacing on the artwork if the OCR reading is confirmed\./, fr: "Corrigez l'espacement sur la maquette si la lecture OCR se confirme.", ar: "صحّح التباعد في التصميم إذا تأكدت قراءة OCR." },
  { re: /Match the approved spacing and punctuation\./, fr: "Reproduisez l'espacement et la ponctuation approuvés.", ar: "طابق التباعد والترقيم المعتمدين." },
  { re: /Match the approved spacing \(for example between a number and its unit\)\./, fr: "Reproduisez l'espacement approuvé (par exemple entre un nombre et son unité).", ar: "طابق التباعد المعتمد (مثلًا بين الرقم ووحدته)." },
  { re: /Confirm the digit style follows your house style and EDA expectations\./, fr: "Confirmez que le style des chiffres suit votre charte et les attentes de l'autorité.", ar: "تأكد أن نمط الأرقام يتبع دليل أسلوبكم ومتطلبات السلطة." },
  { re: /Match the approved punctuation and capitalisation\./, fr: "Reproduisez la ponctuation et les majuscules approuvées.", ar: "طابق الترقيم وحالة الأحرف المعتمدين." },
  { re: /Correct the approved leaflet through change control before it is used as the master\./, fr: "Corrigez le document approuvé par maîtrise des changements avant de l'utiliser comme référence.", ar: "صحّح المستند المعتمد عبر ضبط التغيير قبل استخدامه مرجعًا." },
  { re: /Verify against the source reference \(WHO ATC index \/ originator SmPC\) and correct the master\./, fr: "Vérifiez auprès de la source (index ATC de l'OMS / RCP princeps) et corrigez la référence.", ar: "تحقق من المصدر (فهرس ATC لمنظمة الصحة العالمية / RCP للمنتج الأصلي) وصحّح المرجع." },
  { re: /Check the master leaflet structure against the EDA SmPC\/PIL template\./, fr: "Vérifiez la structure de la notice de référence contre le modèle SmPC/PIL de l'autorité.", ar: "راجع بنية النشرة المرجعية مقابل نموذج SmPC/PIL للسلطة." },
  { re: /Correct the typo in the master leaflet\./, fr: "Corrigez la coquille dans la notice de référence.", ar: "صحّح الخطأ المطبعي في النشرة المرجعية." },
  { re: /Review with the regulatory pharmacist and correct the master if confirmed\./, fr: "À revoir avec le pharmacien des affaires réglementaires ; corriger la référence si c'est confirmé.", ar: "راجعها مع صيدلي الشؤون التنظيمية وصحّح المرجع إذا تأكدت." },
  { re: /Correct the barcode on the artwork, or confirm the change through change control\./, fr: "Corrigez le code-barres sur la maquette, ou confirmez le changement par maîtrise des changements.", ar: "صحّح الباركود على التصميم أو أكّد التغيير عبر ضبط التغيير." },
  { re: /Correct the barcode before the artwork is approved\./, fr: "Corrigez le code-barres avant l'approbation de la maquette.", ar: "صحّح الباركود قبل اعتماد التصميم." },
  { re: /Check whether this packaging type should carry a barcode\./, fr: "Vérifiez si ce type de conditionnement doit porter un code-barres.", ar: "تحقق مما إذا كان هذا النوع من العبوات يجب أن يحمل باركود." },
  { re: /Restore the approved graphic, or confirm the change through change control\./, fr: "Rétablissez le graphisme approuvé, ou confirmez le changement par maîtrise des changements.", ar: "أعد العنصر الرسومي المعتمد أو أكّد التغيير عبر ضبط التغيير." },
  { re: /Enlarge the text or confirm the size is acceptable for this market\./, fr: "Agrandissez le texte ou confirmez que la taille est acceptable pour ce marché.", ar: "كبّر النص أو أكّد أن الحجم مقبول لهذا السوق." },
  { re: /Correct the Braille, or confirm it by touch on the printed item\./, fr: "Corrigez le braille, ou confirmez-le au toucher sur l'imprimé.", ar: "صحّح البرايل أو تأكد منه باللمس على المطبوع." },
  { re: /Move the text away from the fold or cut edge\./, fr: "Éloignez le texte du pli ou du bord de coupe.", ar: "أبعد النص عن خط الطي أو حافة القص." },
  { re: /Check the files \(same artwork, whole page, right way up\) and run again\./, fr: "Vérifiez les fichiers (même maquette, page entière, à l'endroit) et relancez.", ar: "تحقق من الملفات (نفس التصميم، صفحة كاملة، بالاتجاه الصحيح) ثم أعد التشغيل." },
  { re: /Measure the sample again or check the print\./, fr: "Mesurez de nouveau l'échantillon ou vérifiez l'impression.", ar: "أعد قياس العينة أو افحص المطبوع." },
  { re: /No action\./, fr: "Aucune action.", ar: "لا إجراء." },

  // ---- Colour (level 4)
  { re: /^(.*): within the shade range$/, fr: "$1 : dans la plage de teintes", ar: "$1: ضمن نطاق الدرجات" },
  { re: /^(.*): outside the shade range$/, fr: "$1 : hors de la plage de teintes", ar: "$1: خارج نطاق الدرجات" },
  { re: /^(.*): screening only \(photo\)$/, fr: "$1 : dépistage seulement (photo)", ar: "$1: فرز مبدئي فقط (صورة)" },
  { re: /^(.*): not measured$/, fr: "$1 : non mesuré", ar: "$1: لم يُقَس" },
  { re: /Photo screening \(not a pass\/fail measurement\): /, fr: "Dépistage photo (pas une mesure décisive) : ", ar: "فرز بالصورة (ليس قياسًا حاسمًا): " },
  { re: /Check with a scan or a spectrophotometer before deciding\./, fr: "Vérifiez avec une numérisation ou un spectrophotomètre avant de décider.", ar: "تحقق بمسح ضوئي أو بمقياس طيف قبل اتخاذ القرار." },
  { re: /darker than the Dark limit \(ΔE00 ([\d.]+) beyond it\)/, fr: "plus foncé que la limite Foncée (ΔE00 $1 au-delà)", ar: "أغمق من حد الدرجة الغامقة (يتجاوزه ΔE00 $1)" },
  { re: /lighter than the Light limit \(ΔE00 ([\d.]+) beyond it\)/, fr: "plus clair que la limite Claire (ΔE00 $1 au-delà)", ar: "أفتح من حد الدرجة الفاتحة (يتجاوزه ΔE00 $1)" },
  { re: /between Dark and Standard \((\d+)% of the way to Dark\)/, fr: "entre Foncée et Standard ($1 % vers la Foncée)", ar: "بين الغامقة والقياسية ($1% باتجاه الغامقة)" },
  { re: /between Standard and Light \((\d+)% of the way to Light\)/, fr: "entre Standard et Claire ($1 % vers la Claire)", ar: "بين القياسية والفاتحة ($1% باتجاه الفاتحة)" },
  { re: /outside the Dark–Light range by ΔE ([\d.]+) \(hue or chroma differs\)/, fr: "hors de la plage Foncée–Claire de ΔE $1 (teinte ou chroma différents)", ar: "خارج نطاق الغامقة–الفاتحة بمقدار ΔE $1 (اختلاف في الصبغة أو التشبع)" },
  { re: /Sample is ([\d.]+) ΔE away from the Dark–Standard–Light range; ΔE00 to Standard ([\d.]+)\./, fr: "L'échantillon est à $1 ΔE de la plage Foncée–Standard–Claire ; ΔE00 à la Standard $2.", ar: "العينة تبعد $1 ΔE عن نطاق الغامقة–القياسية–الفاتحة؛ وΔE00 إلى القياسية $2." },
  { re: /Too dark \(ΔL\* ([+\-\d.]+)\): reduce ink density \/ film weight\./, fr: "Trop foncé (ΔL* $1) : réduire la densité d'encre / le film.", ar: "غامق أكثر من اللازم (ΔL* $1): قلّل كثافة الحبر / طبقة الفيلم." },
  { re: /Too light \(ΔL\* ([+\-\d.]+)\): increase ink density \/ film weight\./, fr: "Trop clair (ΔL* $1) : augmenter la densité d'encre / le film.", ar: "فاتح أكثر من اللازم (ΔL* $1): زد كثافة الحبر / طبقة الفيلم." },
  { re: /Too red \(Δa\* ([+\-\d.]+)\): less magenta, or a touch more cyan\./, fr: "Trop rouge (Δa* $1) : moins de magenta, ou un peu plus de cyan.", ar: "أحمر زائد (Δa* $1): قلّل الماجنتا أو زد السيان قليلًا." },
  { re: /Too green \(Δa\* ([+\-\d.]+)\): more magenta, or less cyan\./, fr: "Trop vert (Δa* $1) : plus de magenta, ou moins de cyan.", ar: "أخضر زائد (Δa* $1): زد الماجنتا أو قلّل السيان." },
  { re: /Too yellow \(Δb\* ([+\-\d.]+)\): less yellow\./, fr: "Trop jaune (Δb* $1) : moins de jaune.", ar: "أصفر زائد (Δb* $1): قلّل الأصفر." },
  { re: /Too blue \(Δb\* ([+\-\d.]+)\): more yellow, or less cyan\./, fr: "Trop bleu (Δb* $1) : plus de jaune, ou moins de cyan.", ar: "أزرق زائد (Δb* $1): زد الأصفر أو قلّل السيان." },

  // ---- Barcodes (level 5)
  { re: /^(\S+) barcode missing or unreadable$/, fr: "Code-barres $1 manquant ou illisible", ar: "باركود $1 مفقود أو غير مقروء" },
  { re: /^(\S+) data changed$/, fr: "Données $1 modifiées", ar: "تغيّرت بيانات $1" },
  { re: /^(\S+) variable data differs$/, fr: "Données variables $1 différentes", ar: "البيانات المتغيرة لـ $1 مختلفة" },
  { re: /^(\S+) content changed$/, fr: "Contenu $1 modifié", ar: "تغيّر محتوى $1" },
  { re: /^Invalid barcode data on the approved artwork$/, fr: "Données de code-barres non valides sur la maquette approuvée", ar: "بيانات باركود غير صالحة على التصميم المعتمد" },
  { re: /^Invalid barcode data on the test file$/, fr: "Données de code-barres non valides sur le fichier d'essai", ar: "بيانات باركود غير صالحة على ملف الاختبار" },
  { re: /^GTIN does not match the product record$/, fr: "Le GTIN ne correspond pas à la fiche produit", ar: "GTIN لا يطابق سجل المنتج" },
  { re: /^Extra (\S+) barcode on the test file$/, fr: "Code-barres $1 en plus sur le fichier d'essai", ar: "باركود $1 زائد على ملف الاختبار" },
  { re: /^(\S+) barcode data is not valid$/, fr: "Les données du code-barres $1 ne sont pas valides", ar: "بيانات باركود $1 غير صالحة" },
  { re: /^No barcode found on the approved material$/, fr: "Aucun code-barres trouvé sur le matériel approuvé", ar: "لم يُعثر على باركود في المادة المعتمدة" },
  { re: /The approved artwork has a (\S+) code \((.*?)\); none was read on the test file\./, fr: "La maquette approuvée porte un code $1 ($2) ; aucun n'a été lu sur le fichier d'essai.", ar: "التصميم المعتمد يحمل كود $1 ($2)؛ ولم يُقرأ أي منه على ملف الاختبار." },
  { re: /Approved (“[^”]*”), test (“[^”]*”)\./, fr: "Approuvé $1, essai $2.", ar: "المعتمد $1 والاختبار $2." },
  { re: /Test code GTIN (\d+), product record GTIN (\d+)\./, fr: "GTIN du code testé $1, GTIN de la fiche produit $2.", ar: "GTIN في الكود المختبر $1 بينما في سجل المنتج $2." },
  { re: /(“[^”]*”) is not on the approved artwork\./, fr: "$1 n'est pas sur la maquette approuvée.", ar: "$1 غير موجود على التصميم المعتمد." },
  { re: /\. Batch, expiry and serial normally change per print run\./, fr: ". Lot, péremption et numéro de série changent normalement à chaque tirage.", ar: ". التشغيلة وتاريخ الصلاحية والرقم التسلسلي تتغير عادة مع كل طبعة." },
  { re: /GTIN (\d+) has a wrong check digit\./, fr: "Le GTIN $1 a une clé de contrôle erronée.", ar: "GTIN $1 به خانة تحقق خاطئة." },
  { re: /(\S+) (\S+) has a wrong check digit\./, fr: "$1 $2 a une clé de contrôle erronée.", ar: "$1 $2 به خانة تحقق خاطئة." },
  { re: /Unknown application identifier at (“[^”]*”)\./, fr: "Identifiant d'application inconnu à $1.", ar: "مُعرّف تطبيق غير معروف عند $1." },
  { re: /GTIN (\d+) differs from the product record \((\d+)\)\./, fr: "Le GTIN $1 diffère de la fiche produit ($2).", ar: "GTIN $1 يختلف عن سجل المنتج ($2)." },
  { re: /The product has GTIN (\d+) but no barcode was read on this file\./, fr: "Le produit a le GTIN $1 mais aucun code-barres n'a été lu sur ce fichier.", ar: "للمنتج GTIN $1 لكن لم يُقرأ أي باركود في هذا الملف." },

  // ---- Graphics (level 6)
  { re: /^Graphic element missing on the test$/, fr: "Élément graphique manquant sur l'essai", ar: "عنصر رسومي مفقود في الاختبار" },
  { re: /^Graphic element added on the test$/, fr: "Élément graphique ajouté sur l'essai", ar: "عنصر رسومي مُضاف في الاختبار" },
  { re: /^Graphic element changed$/, fr: "Élément graphique modifié", ar: "عنصر رسومي متغيّر" },
  { re: /\((\d+(?:\.\d+)?) mm²\) at the marked position\./, fr: "($1 mm²) à l'endroit marqué.", ar: "($1 مم²) في الموضع المحدد." },

  // ---- Print (level 7)
  { re: /^Text smaller than ([\d.]+) pt$/, fr: "Texte plus petit que $1 pt", ar: "نص أصغر من $1 نقطة" },
  { re: /(\d+) line\(s\) at about ([\d.]+) pt \(from the PDF\); the minimum for this packaging type is ([\d.]+) pt\./, fr: "$1 ligne(s) à environ $2 pt (d'après le PDF) ; le minimum pour ce type de conditionnement est $3 pt.", ar: "$1 سطر/أسطر بنحو $2 نقطة (من ملف PDF)؛ والحد الأدنى لهذا النوع من العبوات $3 نقطة." },
  { re: /(\d+) line\(s\) at about ([\d.]+) pt \(estimated from the scan\); the minimum for this packaging type is ([\d.]+) pt\./, fr: "$1 ligne(s) à environ $2 pt (estimé depuis la numérisation) ; le minimum pour ce type de conditionnement est $3 pt.", ar: "$1 سطر/أسطر بنحو $2 نقطة (تقديرًا من المسح)؛ والحد الأدنى لهذا النوع من العبوات $3 نقطة." },
  { re: /^No Braille found$/, fr: "Aucun braille trouvé", ar: "لا يوجد برايل" },
  { re: /^Braille not visible on the scan$/, fr: "Braille non visible sur la numérisation", ar: "البرايل غير ظاهر في المسح الضوئي" },
  { re: /^Braille does not show the product name$/, fr: "Le braille ne donne pas le nom du produit", ar: "البرايل لا يُظهر اسم المنتج" },
  { re: /^Braille strength not found$/, fr: "Dosage introuvable dans le braille", ar: "التركيز غير موجود في البرايل" },
  { re: /Braille is required for this packaging, but no Braille dots were found on the artwork\./, fr: "Le braille est obligatoire pour ce conditionnement, mais aucun point braille n'a été trouvé sur la maquette.", ar: "البرايل مطلوب لهذه العبوة، لكن لم يُعثر على نقاط برايل في التصميم." },
  { re: /No Braille was detected\. Embossing often does not show on a flat scan: check the printed item by touch\./, fr: "Aucun braille détecté. Le gaufrage n'apparaît souvent pas sur une numérisation à plat : vérifiez l'imprimé au toucher.", ar: "لم يُرصد برايل. النقش البارز كثيرًا ما لا يظهر في المسح المسطح: تحقق من المطبوع باللمس." },
  { re: /Braille reads (“[^”]*”); expected the name (“[^”]*”)\./, fr: "Le braille se lit $1 ; le nom attendu était $2.", ar: "البرايل يُقرأ $1؛ والاسم المتوقع $2." },
  { re: /Braille reads (“[^”]*”); none of the registered strengths \((.*?)\) was read\./, fr: "Le braille se lit $1 ; aucun des dosages enregistrés ($2) n'a été lu.", ar: "البرايل يُقرأ $1؛ ولم يُقرأ أي من التركيزات المسجلة ($2)." },
  { re: /^Text crosses a fold line$/, fr: "Du texte traverse une ligne de pli", ar: "نص يعبر خط الطي" },
  { re: /^Text too close to a cut edge$/, fr: "Texte trop près d'un bord de coupe", ar: "نص قريب جدًا من حافة القص" },
  { re: /(\d+) word\(s\) crosses a fold: /, fr: "$1 mot(s) traversent un pli : ", ar: "$1 كلمة/كلمات تعبر خط الطي: " },
  { re: /(\d+) word\(s\) is within ([\d.]+) mm of a cut edge: /, fr: "$1 mot(s) à moins de $2 mm d'un bord de coupe : ", ar: "$1 كلمة/كلمات على بُعد أقل من $2 مم من حافة القص: " },

  // ---- Check-level failures and AI review prefixes
  { re: /^([A-Za-z ]+) check could not run$/, fr: "Le contrôle « $1 » n'a pas pu s'exécuter", ar: "تعذّر تشغيل فحص «$1»" },
  { re: /The AI called this a misreading, but its own readings of the two images differ; check it by eye\./, fr: "L'IA l'a classé comme erreur de lecture, mais ses propres lectures des deux images diffèrent ; vérifiez à l'œil.", ar: "اعتبرها الذكاء الاصطناعي خطأ قراءة، لكن قراءتيه للصورتين مختلفتان؛ تحقق بالعين." },
  { re: /Most of this text is also in the AI's reading of the approved image, so it is probably there in both files and the lines were matched wrongly; check it by eye\./, fr: "La majeure partie de ce texte figure aussi dans la lecture de l'image approuvée par l'IA ; il est probablement présent dans les deux fichiers et les lignes ont été mal appariées ; vérifiez à l'œil.", ar: "معظم هذا النص موجود أيضًا في قراءة الذكاء الاصطناعي للصورة المعتمدة؛ فهو على الأرجح موجود في الملفين وتم مطابقة الأسطر خطأً؛ تحقق بالعين." },
  { re: /Most of this text is also in the AI's reading of the new image, so it is probably there in both files and the lines were matched wrongly; check it by eye\./, fr: "La majeure partie de ce texte figure aussi dans la lecture de la nouvelle image par l'IA ; il est probablement présent dans les deux fichiers et les lignes ont été mal appariées ; vérifiez à l'œil.", ar: "معظم هذا النص موجود أيضًا في قراءة الذكاء الاصطناعي للصورة الجديدة؛ فهو على الأرجح موجود في الملفين وتم مطابقة الأسطر خطأً؛ تحقق بالعين." },
  { re: /AI review unavailable for this finding: /, fr: "Revue IA indisponible pour ce constat : ", ar: "مراجعة الذكاء الاصطناعي غير متاحة لهذا الاكتشاف: " },

  // ---- Locations ("where")
  { re: /^page (\d+), column (\d+) of (\d+)$/, fr: "page $1, colonne $2 sur $3", ar: "صفحة $1، عمود $2 من $3" },
  { re: /^scan page (\d+), left half$/, fr: "page numérisée $1, moitié gauche", ar: "صفحة ممسوحة $1، النصف الأيسر" },
  { re: /^scan page (\d+), right half$/, fr: "page numérisée $1, moitié droite", ar: "صفحة ممسوحة $1، النصف الأيمن" },
  { re: /^page (\d+)$/, fr: "page $1", ar: "صفحة $1" },
  { re: /^approved text$/, fr: "texte approuvé", ar: "النص المعتمد" },

  // ---- Exclusion reasons
  { re: /^Stamp \/ signature ink removed \(blue\)$/, fr: "Encre de tampon / signature retirée (bleue)", ar: "أُزيل حبر الختم / التوقيع (الأزرق)" },
  { re: /^Rotated block \(print-house \/ artwork info\)$/, fr: "Bloc pivoté (informations d'imprimeur / de maquette)", ar: "كتلة مُدارة (بيانات المطبعة / التصميم)" },
  { re: /^Footer \(page number \/ signature\)$/, fr: "Pied de page (numéro de page / signature)", ar: "تذييل (رقم صفحة / توقيع)" },
  { re: /^Unreadable line \(stamp, handwriting or scan damage\)$/, fr: "Ligne illisible (tampon, écriture manuscrite ou défaut de numérisation)", ar: "سطر غير مقروء (ختم أو كتابة يدوية أو تلف في المسح)" },
  { re: /^Administrative header\/footer$/, fr: "En-tête/pied de page administratif", ar: "ترويسة/تذييل إداري" },
  { re: /^Regulatory header \(EDA admin text\)$/, fr: "En-tête réglementaire (texte administratif de l'autorité)", ar: "ترويسة تنظيمية (نص إداري للسلطة)" },
  { re: /^Print-house tracking code$/, fr: "Code de suivi de l'imprimeur", ar: "كود تتبع المطبعة" },
];

const CATEGORIES: Record<string, { fr: string; ar: string }> = {
  "Strength & composition": { fr: "Dosage et composition", ar: "التركيز والتركيب" },
  "Dose & administration": { fr: "Posologie et administration", ar: "الجرعة وطريقة الاستخدام" },
  "Safety information": { fr: "Informations de sécurité", ar: "معلومات السلامة" },
  "Pharmacology": { fr: "Pharmacologie", ar: "علم الأدوية" },
  "Storage, pack & manufacturer": { fr: "Conservation, emballage et fabricant", ar: "التخزين والعبوة والمصنّع" },
  "General text": { fr: "Texte général", ar: "نص عام" },
  "Master leaflet": { fr: "Notice de référence", ar: "النشرة المرجعية" },
  "AI scientific review": { fr: "Revue scientifique par l'IA", ar: "المراجعة العلمية بالذكاء الاصطناعي" },
  "Colour": { fr: "Couleur", ar: "اللون" },
  "Barcodes": { fr: "Codes-barres", ar: "الباركود" },
  "Graphics & layout": { fr: "Graphismes et mise en page", ar: "الرسوميات والتخطيط" },
  "Print": { fr: "Impression", ar: "الطباعة" },
};

/** Translate one engine-written string. Unknown wording is left as it is. */
export function engineText(s: string | null | undefined, lang: Lang): string {
  if (!s || lang === "en") return s ?? "";
  let out = s;
  for (const r of RULES) out = out.replace(r.re, lang === "fr" ? r.fr : r.ar);
  return out;
}

/** A copy of the finding with Comproof's own words in the interface language.
 *  Document text (ref_text / des_text, OCR readings, quotes inside “ ”) is never translated. */
export function localizeFinding<T extends Record<string, any>>(f: T, lang: Lang): T {
  if (lang === "en") return f;
  const g: any = { ...f };
  for (const k of ["title", "explanation", "action", "note", "where_ref", "where_des"] as const) {
    if (g[k]) g[k] = engineText(g[k], lang);
  }
  if (g.category && CATEGORIES[g.category]) g.category = CATEGORIES[g.category][lang === "fr" ? "fr" : "ar"];
  if (g.ai?.explanation) g.ai = { ...g.ai, explanation: engineText(g.ai.explanation, lang) };
  return g as T;
}
