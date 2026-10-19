"use strict";

// Interface text. Marathi, Hindi and Odia strings are drafts pending native-speaker review.
const I18N = {
  mr: {
    appName: "शासन निर्णय सहाय्यक", tagline: "अधिकृत शासन निर्णय, सोप्या भाषेत", language: "भाषा",
    summaryTitle: "सोप्या भाषेत समजून घ्या", summaryButton: "सारांश तयार करा", askTitle: "प्रश्न विचारा",
    speak: "बोलून विचारा", stop: "थांबवा", ask: "विचारा", sourceTitle: "मूळ दस्तऐवज",
    sourceHint: "सारांशातील पृष्ठ क्रमांकावर क्लिक करा — मूळ दस्तऐवजातील संबंधित मजकूर इथे दिसेल.",
    disclaimer: "हे स्पष्टीकरण आहे, शासनाचा अधिकृत निर्णय नाही. कोणतीही कृती करण्यापूर्वी मूळ शासन निर्णय तपासा.",
    officialSource: "अधिकृत स्रोत", issued: "दिनांक", retrieved: "मिळवले",
    badgeOcrScan: "स्कॅन केलेले पान — OCR ने वाचले", badgeOcrCorrupt: "मूळ मजकूर बिघडलेला — OCR ने पुन्हा वाचले",
    badgeUnverified: n => `${n} आकडे पडताळणी बाकी`, badgeReviewed: n => `${n} भाग व्यक्तीने तपासले`,
    page: n => `पृ. ${n}`, portalListing: "पोर्टल यादी",
    sections: { what: "दस्तऐवज काय सांगतो", applies_to: "कोणाला लागू", eligibility: "पात्रता व अपवाद",
      benefits: "लाभ, दर किंवा रक्कम", documents: "आवश्यक कागदपत्रे", process: "काय करायचे व कोणी",
      dates: "महत्त्वाच्या तारखा", conditions: "अटी व शर्ती", status: "आधीच्या आदेशांशी संबंध" },
    notStated: "या दस्तऐवजात नमूद नाही:", removedNote: n => `स्रोतात आधार न मिळाल्याने ${n} विधाने काढून टाकली.`,
    generatedBy: (m, t) => `${m} द्वारे तयार · ${t}`, loading: "तयार होत आहे",
    errors: { model_not_configured: "स्पष्टीकरण सेवा सध्या जोडलेली नाही. मूळ दस्तऐवज वाचता येईल.",
      model_unavailable: "स्पष्टीकरण सेवा सध्या प्रतिसाद देत नाही. थोड्या वेळाने पुन्हा प्रयत्न करा.",
      tts_unavailable: "आवाज सेवा सध्या उपलब्ध नाही. लिखित उत्तर वैध आहे.",
      stt_unavailable: "आवाज ओळख सेवा सध्या उपलब्ध नाही. कृपया प्रश्न टाइप करा.",
      generic: "काहीतरी चुकले. कृपया पुन्हा प्रयत्न करा." },
    insufficient: "उपलब्ध दस्तऐवजांमधून या प्रश्नाचे उत्तर निश्चित करता येत नाही.",
    failed: "विश्वासार्ह उत्तर तयार करता आले नाही. कृपया पुन्हा प्रयत्न करा.",
    listen: "ऐका", syntheticLabel: "AI-निर्मित आवाज",
    recording: "रेकॉर्डिंग सुरू आहे… बोलून झाल्यावर 'थांबवा' दाबा.", transcribing: "आवाज ओळखत आहे",
    confirmTranscript: "हा प्रश्न बरोबर आहे का? गरज असल्यास दुरुस्त करा आणि 'विचारा' दाबा.",
    feedback: { helpful: "उपयोगी", incorrect: "चुकीचे", unclear: "अस्पष्ट" }, thanks: "धन्यवाद! अभिप्राय नोंदवला.",
    unverifiedLegend: "लाल रेषांकित आकडे OCR मध्ये अस्पष्ट आहेत — मूळ पानावर तपासा.",
    origin: { ocr: "OCR ने वाचलेला मजकूर", reviewed: "व्यक्तीने तपासलेला मजकूर", embedded: "मूळ मजकूर",
      portal_metadata: "अधिकृत पोर्टलवरील माहिती" },
    placeholder: "आपला प्रश्न इथे लिहा", noDocs: "या राज्यासाठी दस्तऐवज अजून उपलब्ध नाहीत.",
    micDenied: "मायक्रोफोन वापरण्याची परवानगी मिळाली नाही.",
    docType: { circular: "परिपत्रक", notification: "अधिसूचना", gr: "शासन निर्णय", uploaded: "अपलोड केलेला दस्तऐवज" },
    uploadsTab: "अपलोड केलेले दस्तऐवज", uploadTitle: "GR / दस्तऐवज अपलोड करा",
    uploadKicker: "नवीन शासन निर्णय जोडा", uploadReady: "सुरक्षित स्थानिक प्रक्रिया", uploadLimit: "कमाल फाइल आकार: 50 MB",
    uploadQuickBtn: "नवीन GR अपलोड करा",
    uploadHint: "कोणतीही PDF, DOCX, TXT, RTF, ODT किंवा इमेज फाइल येथे टाका — किंवा निवडा.",
    dropText: "फाइल येथे ड्रॅग आणि ड्रॉप करा", dropOr: "— किंवा —", browseFiles: "फाइल निवडा",
    uploading: "अपलोड होत आहे…", converting: "प्रक्रिया सुरू आहे…",
    uploadSuccess: "दस्तऐवज यशस्वीरित्या जोडला गेला!", selectDoc: "दस्तऐवज निवडा",
    noUploadsYet: "अजून कोणतेही दस्तऐवज अपलोड केलेले नाहीत. सुरू करण्यासाठी वर फाइल अपलोड करा.",
  },
  hi: {
    appName: "शासकीय आदेश सहायक", tagline: "सरकारी आदेश, आसान भाषा में", language: "भाषा",
    summaryTitle: "आसान भाषा में समझें", summaryButton: "सार तैयार करें", askTitle: "सवाल पूछें",
    speak: "बोलकर पूछें", stop: "रोकें", ask: "पूछें", sourceTitle: "मूल दस्तावेज़",
    sourceHint: "सार में पृष्ठ संख्या पर क्लिक करें — मूल दस्तावेज़ का संबंधित हिस्सा यहाँ दिखेगा।",
    disclaimer: "यह केवल व्याख्या है, सरकार का आधिकारिक निर्णय नहीं। कोई भी कदम उठाने से पहले मूल आदेश ज़रूर देखें।",
    officialSource: "आधिकारिक स्रोत", issued: "दिनांक", retrieved: "प्राप्त किया",
    badgeOcrScan: "स्कैन किया गया पृष्ठ — OCR से पढ़ा गया", badgeOcrCorrupt: "मूल टेक्स्ट खराब — OCR से दोबारा पढ़ा गया",
    badgeUnverified: n => `${n} अंकों का सत्यापन बाकी`, badgeReviewed: n => `${n} हिस्से व्यक्ति द्वारा जाँचे गए`,
    page: n => `पृ. ${n}`, portalListing: "पोर्टल सूची",
    sections: { what: "दस्तावेज़ क्या कहता है", applies_to: "किस पर लागू", eligibility: "पात्रता और अपवाद",
      benefits: "लाभ, दरें या राशि", documents: "ज़रूरी दस्तावेज़", process: "क्या करना है और किसे",
      dates: "महत्वपूर्ण तिथियाँ", conditions: "शर्तें", status: "पिछले आदेशों से संबंध" },
    notStated: "इस दस्तावेज़ में उल्लेख नहीं:", removedNote: n => `स्रोत में आधार न मिलने के कारण ${n} कथन हटाए गए।`,
    generatedBy: (m, t) => `${m} द्वारा तैयार · ${t}`, loading: "तैयार हो रहा है",
    errors: { model_not_configured: "व्याख्या सेवा अभी जुड़ी नहीं है। मूल दस्तावेज़ पढ़ा जा सकता है।",
      model_unavailable: "व्याख्या सेवा अभी जवाब नहीं दे रही। कुछ देर बाद फिर कोशिश करें।",
      tts_unavailable: "आवाज़ सेवा अभी उपलब्ध नहीं है। लिखा हुआ उत्तर मान्य है।",
      stt_unavailable: "आवाज़ पहचान सेवा अभी उपलब्ध नहीं है। कृपया सवाल टाइप करें।",
      generic: "कुछ गड़बड़ हुई। कृपया फिर कोशिश करें।" },
    insufficient: "उपलब्ध दस्तावेज़ों से इस सवाल का उत्तर तय नहीं किया जा सकता।",
    failed: "भरोसेमंद उत्तर तैयार नहीं हो सका। कृपया फिर कोशिश करें।",
    listen: "सुनें", syntheticLabel: "AI-निर्मित आवाज़",
    recording: "रिकॉर्डिंग चल रही है… बोलने के बाद 'रोकें' दबाएँ।", transcribing: "आवाज़ पहचानी जा रही है",
    confirmTranscript: "क्या यह सवाल सही है? ज़रूरत हो तो सुधारें और 'पूछें' दबाएँ।",
    feedback: { helpful: "उपयोगी", incorrect: "गलत", unclear: "अस्पष्ट" }, thanks: "धन्यवाद! आपकी राय दर्ज हुई।",
    unverifiedLegend: "लाल रेखांकित अंक OCR में अस्पष्ट हैं — मूल पृष्ठ पर जाँचें।",
    origin: { ocr: "OCR से पढ़ा गया पाठ", reviewed: "व्यक्ति द्वारा जाँचा गया पाठ", embedded: "मूल पाठ",
      portal_metadata: "आधिकारिक पोर्टल की जानकारी" },
    placeholder: "अपना सवाल यहाँ लिखें", noDocs: "इस राज्य के दस्तावेज़ अभी उपलब्ध नहीं हैं।",
    micDenied: "माइक्रोफ़ोन की अनुमति नहीं मिली।",
    docType: { circular: "परिपत्र", notification: "अधिसूचना", gr: "शासन निर्णय", uploaded: "अपलोड किया गया दस्तावेज़" },
    uploadsTab: "अपलोड किए गए दस्तावेज़", uploadTitle: "GR / दस्तावेज़ अपलोड करें",
    uploadKicker: "नया सरकारी आदेश जोड़ें", uploadReady: "सुरक्षित स्थानीय प्रोसेसिंग", uploadLimit: "अधिकतम फ़ाइल आकार: 50 MB",
    uploadQuickBtn: "नया आदेश अपलोड करें",
    uploadHint: "कोई भी PDF, DOCX, TXT, RTF, ODT या इमेज फ़ाइल यहाँ डालें — या चुनें।",
    dropText: "फ़ाइल यहाँ ड्रैग और ड्रॉप करें", dropOr: "— या —", browseFiles: "फ़ाइल चुनें",
    uploading: "अपलोड हो रहा है…", converting: "प्रोसेस हो रहा है…",
    uploadSuccess: "दस्तावेज़ सफलतापूर्वक जोड़ा गया!", selectDoc: "दस्तावेज़ चुनें",
    noUploadsYet: "अभी तक कोई दस्तावेज़ अपलोड नहीं किया गया है। शुरू करने के लिए ऊपर फ़ाइल अपलोड करें।",
  },
  or: {
    appName: "ସରକାରୀ ଆଦେଶ ସହାୟକ", tagline: "ସରକାରୀ ଆଦେଶ, ସରଳ ଭାଷାରେ", language: "ଭାଷା",
    summaryTitle: "ସରଳ ଭାଷାରେ ବୁଝନ୍ତୁ", summaryButton: "ସାରାଂଶ ପ୍ରସ୍ତୁତ କରନ୍ତୁ", askTitle: "ପ୍ରଶ୍ନ ପଚାରନ୍ତୁ",
    speak: "କହି ପଚାରନ୍ତୁ", stop: "ବନ୍ଦ କରନ୍ତୁ", ask: "ପଚାରନ୍ତୁ", sourceTitle: "ମୂଳ ଦଲିଲ",
    sourceHint: "ସାରାଂଶରେ ପୃଷ୍ଠା ସଂଖ୍ୟା ଉପରେ କ୍ଲିକ କରନ୍ତୁ — ମୂଳ ଦଲିଲର ସମ୍ପୃକ୍ତ ଅଂଶ ଏଠାରେ ଦେଖାଯିବ।",
    disclaimer: "ଏହା କେବଳ ବ୍ୟାଖ୍ୟା, ସରକାରଙ୍କ ଆନୁଷ୍ଠାନିକ ନିଷ୍ପତ୍ତି ନୁହେଁ। କୌଣସି ପଦକ୍ଷେପ ନେବା ପୂର୍ବରୁ ମୂଳ ଆଦେଶ ଦେଖନ୍ତୁ।",
    officialSource: "ସରକାରୀ ଉତ୍ସ", issued: "ତାରିଖ", retrieved: "ସଂଗୃହୀତ",
    badgeOcrScan: "ସ୍କାନ କରାଯାଇଥିବା ପୃଷ୍ଠା — OCR ଦ୍ୱାରା ପଢ଼ାଯାଇଛି", badgeOcrCorrupt: "ମୂଳ ଲେଖା ତ୍ରୁଟିପୂର୍ଣ୍ଣ — OCR ଦ୍ୱାରା ପୁଣି ପଢ଼ାଯାଇଛି",
    badgeUnverified: n => `${n}ଟି ସଂଖ୍ୟା ଯାଞ୍ଚ ବାକି`, badgeReviewed: n => `${n}ଟି ଅଂଶ ବ୍ୟକ୍ତିଙ୍କ ଦ୍ୱାରା ଯାଞ୍ଚ ହୋଇଛି`,
    page: n => `ପୃ. ${n}`, portalListing: "ପୋର୍ଟାଲ ତାଲିକା",
    sections: { what: "ଦଲିଲ କ'ଣ କହୁଛି", applies_to: "କାହା ପାଇଁ ପ୍ରଯୁଜ୍ୟ", eligibility: "ଯୋଗ୍ୟତା ଓ ବ୍ୟତିକ୍ରମ",
      benefits: "ସୁବିଧା, ହାର ବା ରାଶି", documents: "ଆବଶ୍ୟକ କାଗଜପତ୍ର", process: "କ'ଣ କରିବାକୁ ହେବ ଓ କିଏ",
      dates: "ଗୁରୁତ୍ୱପୂର୍ଣ୍ଣ ତାରିଖ", conditions: "ସର୍ତ୍ତାବଳୀ", status: "ପୂର୍ବ ଆଦେଶ ସହ ସମ୍ପର୍କ" },
    notStated: "ଏହି ଦଲିଲରେ ଉଲ୍ଲେଖ ନାହିଁ:", removedNote: n => `ଉତ୍ସରେ ଆଧାର ନ ମିଳିବାରୁ ${n}ଟି ବକ୍ତବ୍ୟ ହଟାଯାଇଛି।`,
    generatedBy: (m, t) => `${m} ଦ୍ୱାରା ପ୍ରସ୍ତୁତ · ${t}`, loading: "ପ୍ରସ୍ତୁତ ହେଉଛି",
    errors: { model_not_configured: "ବ୍ୟାଖ୍ୟା ସେବା ବର୍ତ୍ତମାନ ସଂଯୁକ୍ତ ନାହିଁ। ମୂଳ ଦଲିଲ ପଢ଼ିହେବ।",
      model_unavailable: "ବ୍ୟାଖ୍ୟା ସେବା ବର୍ତ୍ତମାନ ଉତ୍ତର ଦେଉନାହିଁ। କିଛି ସମୟ ପରେ ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।",
      tts_unavailable: "ସ୍ୱର ସେବା ବର୍ତ୍ତମାନ ଉପଲବ୍ଧ ନାହିଁ। ଲିଖିତ ଉତ୍ତର ବୈଧ।",
      stt_unavailable: "ସ୍ୱର ଚିହ୍ନଟ ସେବା ବର୍ତ୍ତମାନ ଉପଲବ୍ଧ ନାହିଁ। ଦୟାକରି ପ୍ରଶ୍ନ ଟାଇପ କରନ୍ତୁ।",
      generic: "କିଛି ଭୁଲ ହେଲା। ଦୟାକରି ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।" },
    insufficient: "ଉପଲବ୍ଧ ଦଲିଲରୁ ଏହି ପ୍ରଶ୍ନର ଉତ୍ତର ନିଶ୍ଚିତ କରାଯାଇପାରିବ ନାହିଁ।",
    failed: "ବିଶ୍ୱସନୀୟ ଉତ୍ତର ପ୍ରସ୍ତୁତ ହୋଇପାରିଲା ନାହିଁ। ଦୟାକରି ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।",
    listen: "ଶୁଣନ୍ତୁ", syntheticLabel: "AI-ସୃଷ୍ଟ ସ୍ୱର",
    recording: "ରେକର୍ଡିଂ ଚାଲିଛି… କହିସାରିବା ପରେ 'ବନ୍ଦ କରନ୍ତୁ' ଦବାନ୍ତୁ।", transcribing: "ସ୍ୱର ଚିହ୍ନଟ ହେଉଛି",
    confirmTranscript: "ଏହି ପ୍ରଶ୍ନ ଠିକ୍ କି? ଆବଶ୍ୟକ ହେଲେ ସଂଶୋଧନ କରି 'ପଚାରନ୍ତୁ' ଦବାନ୍ତୁ।",
    feedback: { helpful: "ଉପଯୋଗୀ", incorrect: "ଭୁଲ", unclear: "ଅସ୍ପଷ୍ଟ" }, thanks: "ଧନ୍ୟବାଦ! ଆପଣଙ୍କ ମତାମତ ଗ୍ରହଣ କରାଗଲା।",
    unverifiedLegend: "ଲାଲ ରେଖାଙ୍କିତ ସଂଖ୍ୟା OCRରେ ଅସ୍ପଷ୍ଟ — ମୂଳ ପୃଷ୍ଠାରେ ଯାଞ୍ଚ କରନ୍ତୁ।",
    origin: { ocr: "OCR ଦ୍ୱାରା ପଢ଼ାଯାଇଥିବା ଲେଖା", reviewed: "ବ୍ୟକ୍ତିଙ୍କ ଦ୍ୱାରା ଯାଞ୍ଚ ହୋଇଥିବା ଲେଖା", embedded: "ମୂଳ ଲେଖା",
      portal_metadata: "ସରକାରୀ ପୋର୍ଟାଲର ତଥ୍ୟ" },
    placeholder: "ଆପଣଙ୍କ ପ୍ରଶ୍ନ ଏଠାରେ ଲେଖନ୍ତୁ", noDocs: "ଏହି ରାଜ୍ୟ ପାଇଁ ଦଲିଲ ଏପର୍ଯ୍ୟନ୍ତ ଉପଲବ୍ଧ ନାହିଁ।",
    micDenied: "ମାଇକ୍ରୋଫୋନ ଅନୁମତି ମିଳିଲା ନାହିଁ।",
    docType: { circular: "ପରିପତ୍ର", notification: "ବିଜ୍ଞପ୍ତି", gr: "ସରକାରୀ ନିଷ୍ପତ୍ତି", uploaded: "ଅପଲୋଡ ହୋଇଥିବା ଦଲିଲ" },
    uploadsTab: "ଅପଲୋଡ ହୋଇଥିବା ଦଲିଲ", uploadTitle: "GR / ଦଲିଲ ଅପଲୋଡ କରନ୍ତୁ",
    uploadKicker: "ନୂଆ ସରକାରୀ ନିଷ୍ପତ୍ତି ଯୋଡ଼ନ୍ତୁ", uploadReady: "ସୁରକ୍ଷିତ ସ୍ଥାନୀୟ ପ୍ରକ୍ରିୟା", uploadLimit: "ସର୍ବାଧିକ ଫାଇଲ୍ ଆକାର: 50 MB",
    uploadQuickBtn: "ନୂତନ ଦଲିଲ ଅପଲୋଡ କରନ୍ତୁ",
    uploadHint: "ଯେକୌଣସି PDF, DOCX, TXT, RTF, ODT ବା ଇମେଜ୍ ଫାଇଲ୍ ଏଠାରେ ପକାନ୍ତୁ — ବା ବାଛନ୍ତୁ।",
    dropText: "ଫାଇଲ୍ ଏଠାରେ ଡ୍ରାଗ୍ ଓ ଡ୍ରପ୍ କରନ୍ତୁ", dropOr: "— କିମ୍ବା —", browseFiles: "ଫାଇଲ୍ ବାଛନ୍ତୁ",
    uploading: "ଅପଲୋଡ ହେଉଛି…", converting: "ପ୍ରକ୍ରିୟା ଚାଲିଛି…",
    uploadSuccess: "ଦଲିଲ ସଫଳତାର ସହ ଯୋଡ଼ାଗଲା!", selectDoc: "ଦଲିଲ ବାଛନ୍ତୁ",
    noUploadsYet: "ଏପର୍ଯ୍ୟନ୍ତ କୌଣସି ଦଲିଲ ଅପଲୋଡ ହୋଇନାହିଁ। ଆରମ୍ଭ କରିବା ପାଇଁ ଉପରେ ଫାଇଲ୍ ଅପଲୋଡ କରନ୍ତୁ।",
  },
  en: {
    appName: "Government Order Assistant", tagline: "Official government orders, in plain language", language: "Language",
    summaryTitle: "Understand it simply", summaryButton: "Create summary", askTitle: "Ask a question",
    speak: "Ask by voice", stop: "Stop", ask: "Ask", sourceTitle: "Original document",
    sourceHint: "Click a page number in the summary to see the matching text from the original document here.",
    disclaimer: "This is an explanation, not an official government decision. Always check the original order before acting.",
    officialSource: "Official source", issued: "Dated", retrieved: "Retrieved",
    badgeOcrScan: "Scanned page — read by OCR", badgeOcrCorrupt: "Original text layer corrupted — re-read by OCR",
    badgeUnverified: n => `${n} numbers awaiting verification`, badgeReviewed: n => `${n} parts checked by a person`,
    page: n => `p. ${n}`, portalListing: "portal listing",
    sections: { what: "What the document says", applies_to: "Who it applies to", eligibility: "Eligibility and exclusions",
      benefits: "Benefits, rates or amounts", documents: "Documents required", process: "What to do, and who does it",
      dates: "Important dates", conditions: "Conditions", status: "Relation to earlier orders" },
    notStated: "Not mentioned in this document:", removedNote: n => `${n} statements were removed because the source did not support them.`,
    generatedBy: (m, t) => `Generated by ${m} · ${t}`, loading: "Preparing",
    errors: { model_not_configured: "The explanation service is not connected right now. You can still read the original document.",
      model_unavailable: "The explanation service is not responding. Please try again shortly.",
      tts_unavailable: "Voice playback is unavailable right now. The written answer is still valid.",
      stt_unavailable: "Voice input is unavailable right now. Please type your question.",
      generic: "Something went wrong. Please try again." },
    insufficient: "The available documents do not establish an answer to this question.",
    failed: "A reliable answer could not be produced. Please try again.",
    listen: "Listen", syntheticLabel: "AI-generated voice",
    recording: "Recording… press 'Stop' when you finish speaking.", transcribing: "Recognising speech",
    confirmTranscript: "Is this your question? Correct it if needed, then press 'Ask'.",
    feedback: { helpful: "Helpful", incorrect: "Incorrect", unclear: "Unclear" }, thanks: "Thank you! Feedback recorded.",
    unverifiedLegend: "Numbers underlined in red were unclear to OCR — check them on the original page.",
    origin: { ocr: "Text read by OCR", reviewed: "Text checked by a person", embedded: "Original text",
      portal_metadata: "Information from the official portal" },
    placeholder: "Type your question here", noDocs: "No documents are available for this state yet.",
    micDenied: "Microphone permission was not granted.",
    docType: { circular: "Circular", notification: "Notification", gr: "Government Resolution", uploaded: "Uploaded Document" },
    uploadsTab: "Uploaded Documents", uploadTitle: "Upload a GR / Document",
    uploadKicker: "ADD A GOVERNMENT RESOLUTION", uploadReady: "Secure local processing", uploadLimit: "Maximum file size: 50 MB",
    uploadQuickBtn: "Upload GR",
    uploadHint: "Drop any PDF, DOCX, TXT, RTF, ODT, or image file here — or click to browse.",
    dropText: "Drag & drop your file here", dropOr: "— or —", browseFiles: "Browse Files",
    uploading: "Uploading…", converting: "Processing document…",
    uploadSuccess: "Document uploaded successfully! Ready for summaries and questions.",
    selectDoc: "Select Document",
    noUploadsYet: "No documents uploaded yet. Upload a document above to get started.",
  },
};

const STATE_LANG = { MH: "mr", MP: "hi", OD: "or", UP: "mr" };
const API = "/api/v1";
const ui = { state: "MH", lang: "mr", doc: null, detail: null, docs: [], passages: {}, lastAnswer: "" };
const $ = sel => document.querySelector(sel);
const t = () => I18N[ui.lang];

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, options = {}) {
  const resp = await fetch(API + path, options);
  let body = null;
  try { body = await resp.json(); } catch { /* non-JSON */ }
  if (!resp.ok || !body || body.error) {
    const code = body && body.error ? body.error.code : "generic";
    const msg = body && body.error ? body.error.message : null;
    const err = new Error(msg || code);
    err.code = code;
    throw err;
  }
  return body;
}

function errorText(err) { return t().errors[err.code] || err.message || t().errors.generic; }

function applyStaticText() {
  document.documentElement.lang = ui.lang;
  document.title = t().appName;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const val = t()[el.dataset.i18n];
    if (typeof val === "string") el.textContent = val;
  });
  $("#question").placeholder = t().placeholder;
  $("#language").value = ui.lang;
  document.querySelectorAll(".states button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.state === ui.state)));
}

function pageLabel(pid) {
  const m = /:p(\d+):/.exec(pid);
  return m ? t().page(m[1]) : t().portalListing;
}

// Browsers often lack Odia month names, so Odia dates are formatted explicitly.
const ODIA_MONTHS = ["ଜାନୁଆରୀ", "ଫେବୃଆରୀ", "ମାର୍ଚ୍ଚ", "ଏପ୍ରିଲ", "ମେ", "ଜୁନ", "ଜୁଲାଇ", "ଅଗଷ୍ଟ", "ସେପ୍ଟେମ୍ବର", "ଅକ୍ଟୋବର", "ନଭେମ୍ବର", "ଡିସେମ୍ବର"];
const odiaDigits = n => String(n).replace(/\d/g, c => "୦୧୨୩୪୫୬୭୮୯"[c]);

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  if (ui.lang === "or") return `${odiaDigits(d.getDate())} ${ODIA_MONTHS[d.getMonth()]} ${odiaDigits(d.getFullYear())}`;
  const locale = { mr: "mr-IN", hi: "hi-IN", en: "en-IN" }[ui.lang] || "en-IN";
  return d.toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric" });
}

// -- document card & selector ------------------------------------------------

function renderDocSwitcher() {
  const switcher = $("#doc-switcher");
  if (!switcher) return;
  if (!ui.docs || ui.docs.length <= 1) {
    switcher.style.display = "none";
    switcher.innerHTML = "";
    return;
  }
  const s = t();
  const options = ui.docs.map(d => {
    const title = ui.lang === "en" ? (d.title_en || d.title) : d.title;
    const sel = d.id === (ui.doc && ui.doc.id) ? " selected" : "";
    return `<option value="${esc(d.id)}"${sel}>${esc(title)} (${esc(d.pages)} ${ui.lang === "mr" ? "पृष्ठे" : "pages"})</option>`;
  }).join("");
  switcher.style.display = "flex";
  switcher.innerHTML = `<label for="doc-select">${esc(s.selectDoc)}:</label>
    <select id="doc-select" data-testid="doc-select">${options}</select>`;
  $("#doc-select").addEventListener("change", e => selectDocument(e.target.value));
}

async function selectDocument(docId) {
  const target = ui.docs.find(d => d.id === docId);
  if (!target) return;
  ui.doc = target;
  ui.detail = null;
  ui.passages = {};
  $("#summary").innerHTML = "";
  $("#answer").innerHTML = "";
  $("#source-body").innerHTML = `<p class="muted">${esc(t().sourceHint)}</p>`;
  const card = $("#doc-card");
  card.innerHTML = `<p class="loading">${esc(t().loading)}</p>`;
  try {
    ui.detail = (await api(`/documents/${encodeURIComponent(ui.doc.id)}`)).data;
    ui.detail.passages.forEach(p => { ui.passages[p.passage_id] = p; });
    renderDocCard();
    renderDocSwitcher();
  } catch (err) {
    card.innerHTML = `<p class="error">${esc(errorText(err))}</p>`;
  }
}

async function loadState(state, lang) {
  ui.state = state;
  ui.lang = lang || STATE_LANG[state] || "mr";
  ui.doc = ui.detail = null;
  ui.docs = [];
  ui.passages = {};
  applyStaticText();
  $("#summary").innerHTML = "";
  $("#answer").innerHTML = "";
  $("#source-body").innerHTML = `<p class="muted">${esc(t().sourceHint)}</p>`;

  // Upload is a primary action, not a hidden state. Keep it visible while an
  // operator reviews an existing document or browses uploaded documents.
  const uploadSec = $("#upload-section");
  if (uploadSec) uploadSec.hidden = false;
  const switcher = $("#doc-switcher");
  if (switcher) switcher.style.display = "none";

  const card = $("#doc-card");
  card.innerHTML = `<p class="loading">${esc(t().loading)}</p>`;
  try {
    const docs = (await api(`/documents?state=${state}`)).data;
    ui.docs = docs;
    if (!docs.length) {
      if (state === "UP") {
        card.innerHTML = `<p class="muted">${esc(t().noUploadsYet)}</p>`;
      } else {
        card.innerHTML = `<p class="muted">${esc(t().noDocs)}</p>`;
      }
      return;
    }
    ui.doc = docs[0];
    ui.detail = (await api(`/documents/${encodeURIComponent(ui.doc.id)}`)).data;
    ui.detail.passages.forEach(p => { ui.passages[p.passage_id] = p; });
    renderDocCard();
    renderDocSwitcher();
  } catch (err) {
    card.innerHTML = `<p class="error">${esc(errorText(err))}</p>`;
  }
}

function renderDocCard() {
  const d = ui.doc, s = t();
  if (!d || !ui.detail) return;
  const reasons = new Set(ui.detail.pages.map(p => p.reason));
  const badges = [];
  if (reasons.has("corrupt_encoding")) badges.push(`<span class="badge warn">${esc(s.badgeOcrCorrupt)}</span>`);
  if (reasons.has("no_text")) badges.push(`<span class="badge warn">${esc(s.badgeOcrScan)}</span>`);
  if (d.untrusted_numbers) badges.push(`<span class="badge warn">${esc(s.badgeUnverified(d.untrusted_numbers))}</span>`);
  if (d.reviewed_passages) badges.push(`<span class="badge ok">${esc(s.badgeReviewed(d.reviewed_passages))}</span>`);
  const title = ui.lang === "en" ? (d.title_en || d.title) : d.title;
  const dept = ui.lang === "en" ? (d.department_en || d.department) : d.department;

  const isFileUri = d.url && d.url.startsWith("file://");
  const sourceLink = isFileUri
    ? `<span>${esc(s.officialSource)}: Local Upload</span>`
    : `<a href="${esc(d.url)}" target="_blank" rel="noopener" data-testid="official-link">${esc(s.officialSource)} ↗</a>`;

  $("#doc-card").innerHTML = `
    <div class="kicker">${esc(s.docType[d.document_type] || d.document_type)} · ${esc(dept)}</div>
    <h1>${esc(title)}</h1>
    <div class="meta">
      <span>${esc(s.issued)}: ${esc(fmtDate(d.issued))}</span>
      <span>${esc(s.retrieved)}: ${esc(fmtDate(d.retrieved_at))}</span>
      ${sourceLink}
    </div>
    <div class="badges">${badges.join("")}</div>`;
}

// -- citations and source panel ---------------------------------------------

function citeButtons(citations) {
  return citations.map(pid => `<button class="cite" data-pid="${esc(pid)}" data-testid="cite">${esc(pageLabel(pid))}</button>`).join("");
}

function markUntrusted(text, spans) {
  let out = "", pos = 0;
  for (const [s, e] of [...spans].sort((a, b) => a[0] - b[0])) {
    if (s < pos) continue;
    out += esc(text.slice(pos, s)) + `<mark class="unverified">${esc(text.slice(s, e))}</mark>`;
    pos = e;
  }
  return out + esc(text.slice(pos));
}

function showSource(pid) {
  const p = ui.passages[pid];
  if (!p) return;
  const s = t();
  const isFileUri = ui.doc && ui.doc.listing_url && ui.doc.listing_url.startsWith("file://");
  const fallbackLink = isFileUri
    ? `<p class="muted">Local Document</p>`
    : `<p class="muted"><a href="${esc(ui.doc.listing_url)}" target="_blank" rel="noopener">${esc(s.officialSource)} ↗</a></p>`;

  const img = p.page > 0
    ? `<img src="${API}/documents/${encodeURIComponent(ui.doc.id)}/pages/${p.page}.png" alt="${esc(pageLabel(pid))}" loading="lazy">`
    : fallbackLink;
  const legend = p.untrusted && p.untrusted.length ? `<p class="hint">${esc(s.unverifiedLegend)}</p>` : "";
  $("#source-body").innerHTML = `
    <div class="badges"><span class="badge">${esc(pageLabel(pid))}</span>
      <span class="badge ${p.origin === "reviewed" ? "ok" : ""}">${esc(s.origin[p.origin] || p.origin)}</span></div>
    <div class="passage" data-testid="passage">${markUntrusted(p.text, p.untrusted || [])}</div>${legend}${img}`;
  if (window.matchMedia("(max-width: 900px)").matches) $("#source-panel").scrollIntoView({ behavior: "smooth" });
}

document.addEventListener("click", e => {
  const btn = e.target.closest(".cite");
  if (btn) showSource(btn.dataset.pid);
});

// -- summary -----------------------------------------------------------------

async function createSummary() {
  if (!ui.doc) return;
  const box = $("#summary"), btn = $("#btn-summary"), s = t();
  btn.disabled = true;
  box.innerHTML = `<p class="loading">${esc(s.loading)}</p>`;
  try {
    const body = await api("/summaries", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: ui.doc.id, language: ui.lang }),
    });
    renderSummary(body);
  } catch (err) {
    box.innerHTML = `<p class="error" data-testid="summary-error">${esc(errorText(err))}</p>`;
  } finally {
    btn.disabled = false;
  }
}

function renderSummary(body) {
  const s = t(), d = body.data;
  if (d.status !== "summarised") { $("#summary").innerHTML = `<p class="error">${esc(s.failed)}</p>`; return; }
  const stated = d.sections.filter(x => x.status === "stated");
  const missing = d.sections.filter(x => x.status !== "stated").map(x => s.sections[x.key]);
  const html = stated.map(sec => `
    <div class="section" data-section="${esc(sec.key)}">
      <h3>${esc(s.sections[sec.key])}</h3>
      ${sec.claims.map(c => `<p class="claim">${esc(c.text)}${citeButtons(c.citations)}</p>`).join("")}
    </div>`).join("");
  const notes = [];
  if (d.removed_claims) notes.push(s.removedNote(d.removed_claims));
  $("#summary").innerHTML = html
    + (missing.length ? `<p class="not-stated">${esc(s.notStated)} ${esc(missing.join(", "))}</p>` : "")
    + notes.map(n => `<p class="note">${esc(n)}</p>`).join("")
    + listenBlock(stated.flatMap(x => x.claims.map(c => c.text)).join(" "), "summary")
    + `<p class="provenance">${esc(s.generatedBy(d.model, fmtDate(d.generated_at)))}</p>`;
}

// -- questions -----------------------------------------------------------------

async function ask(question) {
  const box = $("#answer"), s = t();
  if (!question.trim() || !ui.doc) return;
  $("#btn-ask").disabled = true;
  $("#mic-status").textContent = "";
  box.innerHTML = `<p class="loading">${esc(s.loading)}</p>`;
  try {
    const body = await api("/qa", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, language: ui.lang, document_id: ui.doc.id }),
    });
    const d = body.data;
    if (d.status !== "answered") {
      box.innerHTML = `<p class="note" data-testid="answer-insufficient">${esc(d.status === "failed" ? s.failed : s.insufficient)}</p>`;
      return;
    }
    const text = d.claims.map(c => c.text).join(" ");
    box.innerHTML = d.claims.map(c => `<p class="claim">${esc(c.text)}${citeButtons(c.citations)}</p>`).join("")
      + (d.removed_claims ? `<p class="note">${esc(s.removedNote(d.removed_claims))}</p>` : "")
      + listenBlock(text, "answer") + feedbackBlock();
  } catch (err) {
    box.innerHTML = `<p class="error">${esc(errorText(err))}</p>`;
  } finally {
    $("#btn-ask").disabled = false;
  }
}

$("#ask-form").addEventListener("submit", e => { e.preventDefault(); ask($("#question").value); });

// -- voice input (always confirmed before use) --------------------------------

let recorder = null, chunks = [];

async function toggleMic() {
  const btn = $("#btn-mic"), status = $("#mic-status"), s = t();
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream);
    chunks = [];
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach(tr => tr.stop());
      btn.classList.remove("recording");
      btn.querySelector("[data-i18n]").textContent = s.speak;
      status.textContent = s.transcribing + " …";
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      try {
        const body = await api(`/speech/transcriptions?language=${ui.lang}`, {
          method: "POST", headers: { "Content-Type": blob.type }, body: blob,
        });
        $("#question").value = body.data.text;
        $("#question").focus();
        status.textContent = s.confirmTranscript;
      } catch (err) {
        status.textContent = errorText(err);
      }
    };
    recorder.start();
    btn.classList.add("recording");
    btn.querySelector("[data-i18n]").textContent = s.stop;
    status.textContent = s.recording;
  } catch {
    status.textContent = s.micDenied;
  }
}

$("#btn-mic").addEventListener("click", toggleMic);

// -- listening (synthetic speech, always labelled) ---------------------------

function listenBlock(text, id) {
  return `<div class="listen" data-listen="${esc(id)}">
    <button class="btn" data-speak="${esc(id)}" data-testid="listen-${esc(id)}">🔊 ${esc(t().listen)}</button>
    <span class="synthetic-label">${esc(t().syntheticLabel)}</span>
    <textarea hidden>${esc(text)}</textarea></div>`;
}

document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-speak]");
  if (!btn) return;
  const wrap = btn.closest(".listen");
  const text = wrap.querySelector("textarea").value;
  btn.disabled = true;
  try {
    const job = (await api("/speech/synthesis", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language: ui.lang }),
    })).data;
    let status = job;
    for (let i = 0; i < 240 && !["done", "failed"].includes(status.status); i++) {
      await new Promise(r => setTimeout(r, 1000));
      status = (await api(`/speech/synthesis/${job.job_id}`)).data;
    }
    if (status.status !== "done") throw Object.assign(new Error("tts"), { code: "tts_unavailable" });
    wrap.querySelector("audio")?.remove();
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = `${API}/speech/synthesis/${job.job_id}/audio`;
    audio.dataset.testid = "audio";
    wrap.insertBefore(audio, wrap.querySelector(".synthetic-label"));
    audio.play().catch(() => {});
  } catch (err) {
    wrap.insertAdjacentHTML("beforeend", `<span class="hint">${esc(errorText(err))}</span>`);
  } finally {
    btn.disabled = false;
  }
});

// -- feedback ----------------------------------------------------------------

function feedbackBlock() {
  const f = t().feedback;
  return `<div class="feedback">${Object.entries(f).map(([k, v]) => `<button data-feedback="${k}">${esc(v)}</button>`).join("")}</div>`;
}

document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-feedback]");
  if (!btn) return;
  try {
    await api("/feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: btn.dataset.feedback, language: ui.lang, document_id: ui.doc && ui.doc.id }),
    });
    btn.parentElement.innerHTML = `<span class="hint">${esc(t().thanks)}</span>`;
  } catch { /* feedback is best effort */ }
});

// -- upload pipeline ---------------------------------------------------------

async function uploadFile(file) {
  if (!file) return;
  const s = t();
  const prog = $("#upload-progress");
  const fill = $("#progress-fill");
  const status = $("#upload-status");
  const result = $("#upload-result");

  prog.style.display = "block";
  fill.style.width = "30%";
  status.textContent = `${s.uploading} (${file.name})`;
  result.innerHTML = "";

  const formData = new FormData();
  formData.append("file", file);
  if (ui.state && ui.state !== "UP") {
    formData.append("state", ui.state);
  }

  try {
    fill.style.width = "65%";
    status.textContent = s.converting;

    const resp = await fetch(`${API}/upload`, {
      method: "POST",
      body: formData,
    });
    const body = await resp.json();
    if (!resp.ok || !body || body.error) {
      const code = body && body.error ? body.error.code : "generic";
      const msg = body && body.error ? body.error.message : t().errors.generic;
      throw new Error(msg || code);
    }

    fill.style.width = "100%";
    status.textContent = s.uploadSuccess;
    const resData = body.data;
    result.innerHTML = `
      <div class="upload-result-box" data-testid="upload-success">
        <h3>✓ ${esc(resData.message || s.uploadSuccess)}</h3>
        <div class="meta-grid">
          <span class="label">File:</span><span>${esc(resData.filename)}</span>
          <span class="label">Format:</span><span>${esc((resData.original_format || "").toUpperCase())} ➔ PDF</span>
          <span class="label">Pages:</span><span>${esc(resData.pages)}</span>
          <span class="label">Passages:</span><span>${esc(resData.passages)}</span>
          <span class="label">Language:</span><span>${esc(resData.detected_language)}</span>
        </div>
      </div>`;

    // Refresh state and select the newly uploaded document
    const targetState = ui.state === "UP" ? "UP" : (resData.state || "UP");
    await loadState(targetState);
    if (resData.document_id) {
      await selectDocument(resData.document_id);
    }
  } catch (err) {
    fill.style.width = "100%";
    fill.style.background = "var(--flag)";
    status.textContent = "Upload failed";
    result.innerHTML = `<div class="upload-error-box" data-testid="upload-error">⚠️ ${esc(err.message || errorText(err))}</div>`;
  } finally {
    setTimeout(() => {
      prog.style.display = "none";
      fill.style.width = "0%";
      fill.style.background = "";
    }, 4000);
    const input = $("#file-input");
    if (input) input.value = "";
  }
}

const dropZone = $("#drop-zone");
const fileInput = $("#file-input");
if (dropZone && fileInput) {
  dropZone.tabIndex = 0;
  dropZone.setAttribute("role", "button");
  dropZone.setAttribute("aria-labelledby", "upload-title");
  dropZone.addEventListener("click", e => {
    if (!e.target.closest("label")) fileInput.click();
  });
  dropZone.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  ["dragenter", "dragover"].forEach(evt => {
    dropZone.addEventListener(evt, e => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag-over");
    });
  });
  ["dragleave", "dragend", "drop"].forEach(evt => {
    dropZone.addEventListener(evt, e => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag-over");
    });
  });
  dropZone.addEventListener("drop", e => {
    const dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length) {
      uploadFile(dt.files[0]);
    }
  });
  fileInput.addEventListener("change", e => {
    if (e.target.files && e.target.files.length) {
      uploadFile(e.target.files[0]);
    }
  });
}

// -- wiring ------------------------------------------------------------------

document.querySelectorAll(".states button").forEach(b => b.addEventListener("click", () => loadState(b.dataset.state)));
$("#language").addEventListener("change", e => {
  ui.lang = e.target.value;
  applyStaticText();
  if (ui.detail) {
    renderDocCard();
    renderDocSwitcher();
  }
  $("#summary").innerHTML = "";
  $("#answer").innerHTML = "";
});
$("#btn-summary").addEventListener("click", createSummary);
const btnTopUpload = $("#btn-top-upload");
if (btnTopUpload) {
  btnTopUpload.addEventListener("click", () => {
    $("#upload-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
    fileInput?.click();
  });
}

const params = new URLSearchParams(location.search);
const initialState = params.get("state") in STATE_LANG ? params.get("state") : "MH";
const initialLang = params.get("lang") in I18N ? params.get("lang") : null;
loadState(initialState, initialLang);
