import os
import smtplib
from email.message import EmailMessage
from typing import Optional, List, Dict, Any
from flask import current_app

class EmailDeliveryError(Exception):
    """Error al intentar entregar un correo electrónico."""
    pass

class EmailService:
    """
    Adaptador de correo transaccional desacoplado.
    Soporta dos backends:
    - 'in_memory' (por defecto en entornos de pruebas y QA sin SMTP real):
      Almacena los mensajes en memoria para inspección en tests automatizados.
    - 'smtp' (producción):
      Envío seguro mediante servidor SMTP configurado por variables de entorno.
    """
    def __init__(self):
        self._sent_messages: List[Dict[str, Any]] = []
        self._simulate_failure: bool = False

    def set_simulate_failure(self, value: bool) -> None:
        """Permite a las pruebas simular fallos en el transporte de correo."""
        self._simulate_failure = value

    def clear_sent_messages(self) -> None:
        """Limpia los mensajes almacenados en memoria (para uso en pruebas)."""
        self._sent_messages.clear()

    def get_sent_messages(self) -> List[Dict[str, Any]]:
        """Retorna copia de los mensajes capturados en memoria."""
        return list(self._sent_messages)

    def get_last_token_for(self, email: str) -> Optional[str]:
        """Obtiene el último token de verificación generado para un correo (solo pruebas)."""
        normalized = email.strip().lower()
        for msg in reversed(self._sent_messages):
            if msg.get('to') == normalized:
                return msg.get('token')
        return None

    def _send_transport(self, normalized_email: str, subject: str, text_body: str, html_body: str, memory_dict: Dict[str, Any]) -> None:
        """Entrega el mensaje a través del backend configurado ('in_memory' o 'smtp')."""
        # Si la app está en modo de pruebas (TESTING=True), forzar in_memory para aislamiento de tests
        if current_app.config.get('TESTING'):
            backend = 'in_memory'
        else:
            backend = current_app.config.get('MAIL_BACKEND', 'in_memory').lower()

        if backend == 'in_memory':
            self._sent_messages.append(memory_dict)
            current_app.logger.info(f"Correo encolado en memoria para {normalized_email} (subject='{subject}')")
            return

        elif backend == 'smtp':
            smtp_host = current_app.config.get('SMTP_HOST')
            smtp_port = current_app.config.get('SMTP_PORT', 587)
            smtp_user = current_app.config.get('SMTP_USER')
            smtp_pass = current_app.config.get('SMTP_PASSWORD')
            smtp_from = current_app.config.get('SMTP_FROM', 'Afinia <no-reply@afinia.app>')
            use_tls = current_app.config.get('SMTP_USE_TLS', True)

            if not smtp_host:
                raise EmailDeliveryError("Configuración SMTP_HOST ausente para el backend 'smtp'.")

            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = smtp_from
            msg['To'] = normalized_email
            msg.set_content(text_body)
            msg.add_alternative(html_body, subtype='html')

            try:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=12) as server:
                    if use_tls:
                        server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                current_app.logger.info(f"Correo enviado exitosamente vía SMTP a {normalized_email}")
            except Exception as e:
                current_app.logger.error(f"Error al enviar correo SMTP a {normalized_email}: {str(e)}")
                raise EmailDeliveryError(f"Error de transporte SMTP: {str(e)}")
        else:
            raise EmailDeliveryError(f"Backend de correo '{backend}' no reconocido.")

    def send_auth_code_email(self, to_email: str, code: str, user_name: Optional[str] = None) -> None:
        """
        Envía un correo con el código OTP de autenticación / verificación.
        Plantilla estilizada con identidad Afinia (corazones, gradientes y diseño responsivo).
        """
        if self._simulate_failure:
            raise EmailDeliveryError("Fallo simulado en el transporte de correo transaccional.")

        normalized_email = to_email.strip().lower()
        greeting = f"Hola {user_name}," if user_name else "¡Hola!"

        subject = f"💖 Tu código de acceso a Afinia: {code}"

        text_body = (
            f"{greeting}\n\n"
            f"Tu código de verificación para Afinia es:\n\n"
            f"    {code}\n\n"
            f"Este código es válido por 10 minutos y es de uso único.\n\n"
            f"Si tú no solicitaste este código, puedes ignorar este mensaje de forma segura.\n"
            f"Nunca compartas este código con nadie.\n\n"
            f"— El equipo de Afinia 💕"
        )

        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FFF1F4; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #FFF1F4; padding: 40px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 540px; background-color: #FFFFFF; border-radius: 24px; overflow: hidden; box-shadow: 0 12px 36px rgba(230, 46, 92, 0.12); border: 1px solid #FFE4E9;">
          <tr>
            <td align="center" style="background: linear-gradient(135deg, #FF3366 0%, #FF6584 50%, #8A2387 100%); padding: 42px 20px 32px 20px; text-align: center;">
              <div style="font-size: 38px; line-height: 38px; margin-bottom: 12px;">💖 ✨ 💕</div>
              <h1 style="color: #FFFFFF; font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px;">Afinia</h1>
              <p style="color: #FFE4EC; font-size: 13px; margin: 6px 0 0 0; font-weight: 500; letter-spacing: 0.5px;">CONECTA CON QUIEN COMPARTE TU ENERGÍA</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 36px 32px 28px 32px; text-align: center;">
              <h2 style="color: #1F2937; font-size: 20px; font-weight: 700; margin: 0 0 12px 0;">{greeting}</h2>
              <p style="color: #4B5563; font-size: 15px; line-height: 24px; margin: 0 0 28px 0;">
                Usa el siguiente código de seguridad para verificar tu cuenta e ingresar a <strong>Afinia</strong>:
              </p>
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" align="center" style="margin: 0 auto 28px auto;">
                <tr>
                  <td align="center" style="background: #FFF5F7; border: 2px dashed #FF4D79; border-radius: 18px; padding: 18px 36px;">
                    <span style="font-family: 'Courier New', Courier, monospace, sans-serif; font-size: 34px; font-weight: 800; color: #E11D48; letter-spacing: 8px; display: inline-block; padding-left: 8px;">
                      {code}
                    </span>
                  </td>
                </tr>
              </table>
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" align="center" style="margin: 0 auto 24px auto;">
                <tr>
                  <td style="background-color: #FFF0F3; border-radius: 30px; padding: 6px 16px;">
                    <p style="color: #BE123C; font-size: 13px; font-weight: 600; margin: 0;">⏰ Este código expira en <strong>10 minutos</strong></p>
                  </td>
                </tr>
              </table>
              <p style="color: #9CA3AF; font-size: 13px; line-height: 20px; margin: 0 0 8px 0;">
                🔒 Si tú no solicitaste este código, puedes ignorar este correo; tu cuenta permanecerá totalmente protegida.
              </p>
              <p style="color: #9CA3AF; font-size: 12px; margin: 0;">
                <em>Nunca compartas este código con nadie. El equipo de Afinia jamás te lo solicitará.</em>
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding: 0 32px;"><hr style="border: 0; height: 1px; background-color: #FEE2E2; margin: 0;"></td>
          </tr>
          <tr>
            <td style="padding: 24px 32px 32px 32px; text-align: center; background-color: #FAFAFA;">
              <p style="color: #6B7280; font-size: 13px; margin: 0 0 6px 0; font-weight: 500;">
                Hecho con <span style="color: #FF3366;">❤️</span> para que encuentres tu match ideal
              </p>
              <p style="color: #9CA3AF; font-size: 12px; margin: 0;">© 2026 Afinia • Todos los derechos reservados.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        memory_dict = {
            'type': 'auth_code',
            'to': normalized_email,
            'subject': subject,
            'code': code,
            'text_body': text_body,
            'html_body': html_body
        }

        self._send_transport(normalized_email, subject, text_body, html_body, memory_dict)

    def send_verification_email(self, to_email: str, raw_token: str) -> None:
        """
        Envía un correo de verificación transaccional.
        NOTA DE SEGURIDAD: Nunca registra el raw_token en los logs del servidor.
        """
        if self._simulate_failure:
            raise EmailDeliveryError("Fallo simulado en el transporte de correo transaccional.")

        normalized_email = to_email.strip().lower()

        # Determinar URL del frontend configurada por entorno con validación de orígenes
        configured_frontend = current_app.config.get('FRONTEND_URL', 'http://localhost:8100').rstrip('/')
        allowed_origins = current_app.config.get('CORS_ORIGINS', [])
        if allowed_origins and '*' not in allowed_origins and not any(configured_frontend == o.rstrip('/') or configured_frontend.startswith(o.rstrip('/')) for o in allowed_origins):
            frontend_url = 'http://localhost:8100'
        else:
            frontend_url = configured_frontend

        # Uso del fragmento URL (#token=) para evitar que el token viaje en logs HTTP de servidores web intermedios
        verification_url = f"{frontend_url}/verify-email#token={raw_token}"

        subject = "Verifica tu correo electrónico en Afinia"
        
        text_body = (
            f"¡Hola!\n\n"
            f"Gracias por registrarte en Afinia. Para confirmar tu cuenta y continuar con tu perfil, "
            f"por favor ingresa al siguiente enlace de verificación:\n\n"
            f"{verification_url}\n\n"
            f"Este enlace tiene una vigencia temporal de 24 horas y solo puede utilizarse una vez.\n\n"
            f"Si no creaste una cuenta en Afinia, puedes ignorar este mensaje de forma segura.\n\n"
            f"— El equipo de Afinia 💕"
        )

        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FFF1F4; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #FFF1F4; padding: 40px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 540px; background-color: #FFFFFF; border-radius: 24px; overflow: hidden; box-shadow: 0 12px 36px rgba(230, 46, 92, 0.12); border: 1px solid #FFE4E9;">
          <tr>
            <td align="center" style="background: linear-gradient(135deg, #FF3366 0%, #FF6584 50%, #8A2387 100%); padding: 42px 20px 32px 20px; text-align: center;">
              <div style="font-size: 38px; line-height: 38px; margin-bottom: 12px;">💖 ✨ 💕</div>
              <h1 style="color: #FFFFFF; font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px;">Afinia</h1>
              <p style="color: #FFE4EC; font-size: 13px; margin: 6px 0 0 0; font-weight: 500; letter-spacing: 0.5px;">CONECTA CON QUIEN COMPARTE TU ENERGÍA</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 36px 32px 28px 32px; text-align: center;">
              <h2 style="color: #1F2937; font-size: 20px; font-weight: 700; margin: 0 0 12px 0;">¡Te damos la bienvenida!</h2>
              <p style="color: #4B5563; font-size: 15px; line-height: 24px; margin: 0 0 28px 0;">
                Para verificar tu dirección de correo electrónico y continuar configurando tu perfil, haz clic en el siguiente botón:
              </p>
              <p style="text-align: center; margin: 30px 0;">
                <a href="{verification_url}" style="background: linear-gradient(135deg, #FF3366 0%, #E11D48 100%); color: #FFFFFF; padding: 14px 32px; text-decoration: none; border-radius: 30px; font-weight: bold; font-size: 16px; display: inline-block; box-shadow: 0 6px 18px rgba(225, 29, 72, 0.35);">
                  ✨ Verificar mi correo
                </a>
              </p>
              <p style="font-size: 13px; color: #777; margin: 24px 0 16px 0;">O copia y pega el siguiente enlace en tu navegador:<br>
                <a href="{verification_url}" style="color: #E11D48; word-break: break-all;">{verification_url}</a>
              </p>
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" align="center" style="margin: 0 auto 24px auto;">
                <tr>
                  <td style="background-color: #FFF0F3; border-radius: 30px; padding: 6px 16px;">
                    <p style="color: #BE123C; font-size: 13px; font-weight: 600; margin: 0;">⏰ Enlace válido por <strong>24 horas</strong> (de uso único)</p>
                  </td>
                </tr>
              </table>
              <p style="color: #9CA3AF; font-size: 12px; margin: 0;">Si no creaste esta cuenta, puedes desestimar este mensaje con total seguridad.</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 0 32px;"><hr style="border: 0; height: 1px; background-color: #FEE2E2; margin: 0;"></td>
          </tr>
          <tr>
            <td style="padding: 24px 32px 32px 32px; text-align: center; background-color: #FAFAFA;">
              <p style="color: #6B7280; font-size: 13px; margin: 0 0 6px 0; font-weight: 500;">
                Hecho con <span style="color: #FF3366;">❤️</span> para que encuentres tu match ideal
              </p>
              <p style="color: #9CA3AF; font-size: 12px; margin: 0;">© 2026 Afinia • Todos los derechos reservados.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        memory_dict = {
            'to': normalized_email,
            'subject': subject,
            'verification_url': verification_url,
            'token': raw_token,
            'text_body': text_body,
            'html_body': html_body
        }

        self._send_transport(normalized_email, subject, text_body, html_body, memory_dict)

    def get_last_password_reset_token_for(self, email: str) -> Optional[str]:
        """Obtiene el último token de restablecimiento de contraseña generado para un correo (solo pruebas)."""
        normalized = email.strip().lower()
        for msg in reversed(self._sent_messages):
            if msg.get('to') == normalized and msg.get('type') == 'password_reset':
                return msg.get('token')
        return None

    def send_password_reset_email(self, to_email: str, raw_token: str) -> None:
        """
        Envía un correo con el enlace seguro de restablecimiento de contraseña.
        NOTA DE SEGURIDAD:
        - Nunca registra el raw_token en los logs del servidor.
        - Utiliza fragmento de URL (#token=) para evitar fugas en cabeceras Referer o logs HTTP.
        - La URL base se valida estrictamente contra la lista de orígenes autorizados.
        """
        if self._simulate_failure:
            raise EmailDeliveryError("Fallo simulado en el transporte de correo transaccional.")

        normalized_email = to_email.strip().lower()

        # Determinar y validar URL base del frontend sujeta a orígenes autorizados
        configured_frontend = current_app.config.get('FRONTEND_URL', 'http://localhost:8100').rstrip('/')
        allowed_origins = current_app.config.get('CORS_ORIGINS', [])
        
        # Validar que frontend_url esté dentro de los orígenes autorizados o usar default seguro
        if allowed_origins and '*' not in allowed_origins and not any(configured_frontend == o.rstrip('/') or configured_frontend.startswith(o.rstrip('/')) for o in allowed_origins):
            frontend_url = 'http://localhost:8100'
        else:
            frontend_url = configured_frontend

        reset_url = f"{frontend_url}/reset-password#token={raw_token}"
        minutes = current_app.config.get('PASSWORD_RESET_TOKEN_MINUTES', 20)

        subject = "Restablece tu contraseña en Afinia"

        text_body = (
            f"¡Hola!\n\n"
            f"Hemos recibido una solicitud para restablecer la contraseña de tu cuenta en Afinia.\n"
            f"Para ingresar una nueva contraseña, por favor ingresa al siguiente enlace:\n\n"
            f"{reset_url}\n\n"
            f"Este enlace tiene una vigencia temporal de {minutes} minutos y solo puede utilizarse una vez.\n\n"
            f"Si tú no solicitaste este cambio, puedes ignorar este mensaje de forma segura: "
            f"tu contraseña actual permanecerá sin modificaciones y tu cuenta seguirá protegida.\n\n"
            f"— El equipo de Afinia 💕"
        )

        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FFF1F4; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #FFF1F4; padding: 40px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 540px; background-color: #FFFFFF; border-radius: 24px; overflow: hidden; box-shadow: 0 12px 36px rgba(230, 46, 92, 0.12); border: 1px solid #FFE4E9;">
          <tr>
            <td align="center" style="background: linear-gradient(135deg, #FF3366 0%, #FF6584 50%, #8A2387 100%); padding: 42px 20px 32px 20px; text-align: center;">
              <div style="font-size: 38px; line-height: 38px; margin-bottom: 12px;">💖 ✨ 💕</div>
              <h1 style="color: #FFFFFF; font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px;">Afinia</h1>
              <p style="color: #FFE4EC; font-size: 13px; margin: 6px 0 0 0; font-weight: 500; letter-spacing: 0.5px;">RECUPERACIÓN DE ACCESO SEGURO</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 36px 32px 28px 32px; text-align: center;">
              <h2 style="color: #1F2937; font-size: 20px; font-weight: 700; margin: 0 0 12px 0;">Restablece tu contraseña</h2>
              <p style="color: #4B5563; font-size: 15px; line-height: 24px; margin: 0 0 28px 0;">
                Hemos recibido una solicitud para cambiar la contraseña de tu cuenta. Haz clic en el botón de abajo para elegir una nueva:
              </p>
              <p style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}" style="background: linear-gradient(135deg, #FF3366 0%, #E11D48 100%); color: #FFFFFF; padding: 14px 32px; text-decoration: none; border-radius: 30px; font-weight: bold; font-size: 16px; display: inline-block; box-shadow: 0 6px 18px rgba(225, 29, 72, 0.35);">
                  🔒 Restablecer mi contraseña
                </a>
              </p>
              <p style="font-size: 13px; color: #777; margin: 24px 0 16px 0;">O copia y pega el siguiente enlace en tu navegador:<br>
                <a href="{reset_url}" style="color: #E11D48; word-break: break-all;">{reset_url}</a>
              </p>
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" align="center" style="margin: 0 auto 24px auto;">
                <tr>
                  <td style="background-color: #FFF0F3; border-radius: 30px; padding: 6px 16px;">
                    <p style="color: #BE123C; font-size: 13px; font-weight: 600; margin: 0;">⏰ Enlace válido por <strong>{minutes} minutos</strong> (de uso único)</p>
                  </td>
                </tr>
              </table>
              <p style="color: #9CA3AF; font-size: 12px; margin: 0;">Si no solicitaste este cambio, no te preocupes: tu contraseña actual sigue segura.</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 0 32px;"><hr style="border: 0; height: 1px; background-color: #FEE2E2; margin: 0;"></td>
          </tr>
          <tr>
            <td style="padding: 24px 32px 32px 32px; text-align: center; background-color: #FAFAFA;">
              <p style="color: #6B7280; font-size: 13px; margin: 0 0 6px 0; font-weight: 500;">
                Hecho con <span style="color: #FF3366;">❤️</span> para que encuentres tu match ideal
              </p>
              <p style="color: #9CA3AF; font-size: 12px; margin: 0;">© 2026 Afinia • Todos los derechos reservados.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        memory_dict = {
            'type': 'password_reset',
            'to': normalized_email,
            'subject': subject,
            'reset_url': reset_url,
            'token': raw_token,
            'text_body': text_body,
            'html_body': html_body
        }

        self._send_transport(normalized_email, subject, text_body, html_body, memory_dict)

email_service = EmailService()
