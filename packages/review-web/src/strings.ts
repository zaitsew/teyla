/** Every word review mode says, in English, Russian and Spanish. The English is the iOS wording
 *  (packages/review-ios Core/ReviewStrings.swift). This file holds tester-facing product text in
 *  other languages, so it is on the leak check's Cyrillic allow-list. A product may replace any key
 *  through `init({ strings })`. */

export interface ReviewStrings {
  button: string;
  modeTitle: string;
  modeHint: string;
  commentTitle: string;
  spotChosen: string;
  areaChosen: string;
  wholeScreen: string;
  next: string;
  exit: string;
  back: string;
  placeholder: string;
  dictate: string;
  listening: string;
  microphoneUnavailable: string;
  send: string;
  retry: string;
  saving: string;
  saveFailed: string;
  pictureFailed: string;
  sentTitle: string;
  sentDetail: string;
  savedTitle: string;
  savedDetail: string;
  done: string;
  noticeTitle: string;
  noticeCaptured: string;
  noticeRecipient: string;
  noticeWhy: string;
  noticeRetention: string;
  noticeOK: string;
  noticeCancel: string;
  previewCaption: string;
  healthConsent: string;
}

export type Language = "en" | "ru" | "es";

const en: ReviewStrings = {
  button: "Review",
  modeTitle: "Review mode",
  modeHint: "The page is paused. Click a spot or drag over an area.",
  commentTitle: "What is wrong here?",
  spotChosen: "Spot chosen. Click elsewhere to change it.",
  areaChosen: "Area chosen. Drag again to change it.",
  wholeScreen: "About the whole screen",
  next: "Next",
  exit: "Exit",
  back: "Back",
  placeholder: "Write what is wrong",
  dictate: "Dictate",
  listening: "Listening. Press the microphone to stop.",
  microphoneUnavailable: "The microphone is not available. Please type instead.",
  send: "Send",
  retry: "Retry",
  saving: "Saving",
  saveFailed:
    "Could not save the capture in this browser. Your comment and the screenshot are still here. Free some space, then press Retry.",
  pictureFailed: "Could not take a picture of this page. Nothing was sent.",
  sentTitle: "Sent. Thank you!",
  sentDetail: "Your comment and the screenshot are on their way.",
  savedTitle: "Saved in this browser",
  savedDetail: "It has not been sent yet. It will be sent again when the review server can be reached.",
  done: "Done",
  noticeTitle: "Before you send",
  noticeCaptured:
    "What is sent: a picture of this page exactly as it looks now, your comment, the name and build of this app, the browser and system, and the element you pointed at. The picture shows everything on the page, including other people's names or data when they are visible.",
  noticeRecipient: "Who gets it: the developer of this app, through a review server. Nobody else.",
  noticeWhy: "Why: to find and fix what you pointed at.",
  noticeRetention:
    "How long: the copy on the server is deleted when the developer's Mac next collects it, usually within the hour. The developer's Mac keeps its copy for 30 days after the report is closed, or 90 days if it is never opened.",
  noticeOK: "OK, send",
  noticeCancel: "Cancel",
  previewCaption: "This picture is what is sent. Black boxes hide private areas.",
  healthConsent: "This page may show my health data. I agree to send it for review.",
};

const ru: ReviewStrings = {
  button: "Замечание",
  modeTitle: "Режим замечаний",
  modeHint: "Страница остановлена. Нажмите на место или выделите область.",
  commentTitle: "Что здесь не так?",
  spotChosen: "Место выбрано. Нажмите в другом месте, чтобы изменить.",
  areaChosen: "Область выбрана. Выделите заново, чтобы изменить.",
  wholeScreen: "Про весь экран",
  next: "Далее",
  exit: "Выйти",
  back: "Назад",
  placeholder: "Напишите, что не так",
  dictate: "Продиктовать",
  listening: "Слушаю. Нажмите на микрофон, чтобы остановить.",
  microphoneUnavailable: "Микрофон недоступен. Напишите текстом.",
  send: "Отправить",
  retry: "Повторить",
  saving: "Сохраняю",
  saveFailed:
    "Не удалось сохранить замечание в этом браузере. Ваш комментарий и снимок экрана остались здесь. Освободите место и нажмите «Повторить».",
  pictureFailed: "Не удалось снять эту страницу. Ничего не отправлено.",
  sentTitle: "Отправлено. Спасибо!",
  sentDetail: "Ваш комментарий и снимок экрана в пути.",
  savedTitle: "Сохранено в этом браузере",
  savedDetail: "Пока не отправлено. Оно уйдёт позже, когда сервер замечаний станет доступен.",
  done: "Готово",
  noticeTitle: "Перед отправкой",
  noticeCaptured:
    "Что отправляется: снимок этой страницы в том виде, как она выглядит сейчас, ваш комментарий, название и сборка приложения, браузер и система, а также элемент, на который вы указали. На снимке видно всё, что есть на странице, в том числе чужие имена и данные, если они на виду.",
  noticeRecipient: "Кто получает: разработчик этого приложения через сервер замечаний. Больше никто.",
  noticeWhy: "Зачем: чтобы найти и исправить то, на что вы указали.",
  noticeRetention:
    "Как долго: копия на сервере удаляется в течение часа. Копия на Mac разработчика хранится 30 дней после закрытия замечания или 90 дней, если его так и не открыли.",
  noticeOK: "Хорошо, отправить",
  noticeCancel: "Отмена",
  previewCaption: "Отправляется именно этот снимок. Чёрные блоки скрывают личные области.",
  healthConsent: "На этой странице могут быть мои данные о здоровье. Я согласен(на) отправить их на проверку.",
};

const es: ReviewStrings = {
  button: "Revisar",
  modeTitle: "Modo de revisión",
  modeHint: "La página está en pausa. Haz clic en un punto o arrastra sobre un área.",
  commentTitle: "¿Qué falla aquí?",
  spotChosen: "Punto elegido. Haz clic en otro sitio para cambiarlo.",
  areaChosen: "Área elegida. Arrastra de nuevo para cambiarla.",
  wholeScreen: "Sobre toda la pantalla",
  next: "Siguiente",
  exit: "Salir",
  back: "Atrás",
  placeholder: "Escribe qué falla",
  dictate: "Dictar",
  listening: "Escuchando. Pulsa el micrófono para parar.",
  microphoneUnavailable: "El micrófono no está disponible. Escribe el texto.",
  send: "Enviar",
  retry: "Reintentar",
  saving: "Guardando",
  saveFailed:
    "No se pudo guardar la captura en este navegador. Tu comentario y la imagen siguen aquí. Libera espacio y pulsa Reintentar.",
  pictureFailed: "No se pudo hacer una imagen de esta página. No se envió nada.",
  sentTitle: "Enviado. ¡Gracias!",
  sentDetail: "Tu comentario y la imagen van de camino.",
  savedTitle: "Guardado en este navegador",
  savedDetail: "Aún no se ha enviado. Se enviará de nuevo cuando se pueda llegar al servidor de revisión.",
  done: "Hecho",
  noticeTitle: "Antes de enviar",
  noticeCaptured:
    "Qué se envía: una imagen de esta página tal como se ve ahora, tu comentario, el nombre y la versión de esta aplicación, el navegador y el sistema, y el elemento que señalaste. La imagen muestra todo lo que hay en la página, incluidos nombres o datos de otras personas si están a la vista.",
  noticeRecipient: "Quién lo recibe: quien desarrolla esta aplicación, a través de un servidor de revisión. Nadie más.",
  noticeWhy: "Para qué: para encontrar y arreglar lo que señalaste.",
  noticeRetention:
    "Cuánto tiempo: la copia del servidor desaparece en menos de una hora. El Mac de quien desarrolla guarda su copia 30 días después de cerrar el informe, o 90 días si nunca se abre.",
  noticeOK: "De acuerdo, enviar",
  noticeCancel: "Cancelar",
  previewCaption: "Esta imagen es la que se envía. Los recuadros negros ocultan las áreas privadas.",
  healthConsent: "Esta página puede mostrar mis datos de salud. Acepto enviarlos para su revisión.",
};

export const STRINGS: Record<Language, ReviewStrings> = { en, ru, es };

export function pickLanguage(requested: string | undefined | null): Language {
  const code = (requested ?? "").toLowerCase().split(/[-_]/)[0];
  return code === "ru" || code === "es" ? code : "en";
}

export function stringsFor(language: string | undefined | null, overrides?: Partial<ReviewStrings>): ReviewStrings {
  return { ...STRINGS[pickLanguage(language)], ...(overrides ?? {}) };
}

/** The notice as one text, in the order a reader needs it. */
export function noticeMessage(s: ReviewStrings): string {
  return [s.noticeCaptured, s.noticeRecipient, s.noticeWhy, s.noticeRetention].join("\n\n");
}
