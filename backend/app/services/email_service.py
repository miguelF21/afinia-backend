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

    def send_verification_email(self, to_email: str, raw_token: str) -> None:
        """
        Envía un correo de verificación transaccional.
        NOTA DE SEGURIDAD: Nunca registra el raw_token en los logs del servidor.
        """
        if self._simulate_failure:
            raise EmailDeliveryError("Fallo simulado en el transporte de correo transaccional.")

        normalized_email = to_email.strip().lower()

        # Determinar URL del frontend configurada por entorno
        frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:8100').rstrip('/')
        # Uso del fragmento URL (#token=) para evitar que el token viaje en logs HTTP de servidores web intermedios
        verification_url = f"{frontend_url}/verify-email#token={raw_token}"

        subject = "Verifica tu correo electrónico en Afinia"
        
        text_body = (
            f"Hola,\n\n"
            f"Gracias por registrarte en Afinia. Para confirmar tu cuenta y continuar con tu perfil, "
            f"por favor ingresa al siguiente enlace de verificación:\n\n"
            f"{verification_url}\n\n"
            f"Este enlace tiene una vigencia temporal de 24 horas y solo puede utilizarse una vez.\n\n"
            f"Si no creaste una cuenta en Afinia, puedes ignorar este mensaje de forma segura.\n\n"
            f"— El equipo de Afinia"
        )

        html_body = (
            f"<div style='font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;'>"
            f"<h2 style='color: #4A90E2;'>Bienvenido a Afinia</h2>"
            f"<p>Para verificar tu dirección de correo electrónico y continuar configurando tu cuenta, "
            f"haz clic en el siguiente botón:</p>"
            f"<p style='text-align: center; margin: 30px 0;'>"
            f"<a href='{verification_url}' style='background-color: #4A90E2; color: #fff; padding: 12px 24px; "
            f"text-decoration: none; border-radius: 6px; font-weight: bold;'>Verificar mi correo</a>"
            f"</p>"
            f"<p style='font-size: 13px; color: #777;'>O copia y pega el siguiente enlace en tu navegador:<br>"
            f"<a href='{verification_url}' style='color: #4A90E2; word-break: break-all;'>{verification_url}</a></p>"
            f"<p style='font-size: 12px; color: #999; margin-top: 30px;'>"
            f"Este enlace expira en 24 horas y es de uso único.<br>"
            f"Si tú no creaste esta cuenta, puedes desestimar este mensaje con total seguridad."
            f"</p>"
            f"</div>"
        )

        backend = current_app.config.get('MAIL_BACKEND', 'in_memory').lower()

        if backend == 'in_memory':
            # Registro en memoria seguro para QA / automatización de pruebas
            self._sent_messages.append({
                'to': normalized_email,
                'subject': subject,
                'verification_url': verification_url,
                'token': raw_token,
                'text_body': text_body,
                'html_body': html_body
            })
            current_app.logger.info(f"Correo de verificación encolado en memoria para {normalized_email}")
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
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    if use_tls:
                        server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                current_app.logger.info(f"Correo de verificación enviado vía SMTP a {normalized_email}")
            except Exception as e:
                current_app.logger.error(f"Error al enviar correo SMTP a {normalized_email}: {str(e)}")
                raise EmailDeliveryError(f"Error de transporte SMTP: {str(e)}")
        else:
            raise EmailDeliveryError(f"Backend de correo '{backend}' no reconocido.")

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
        if allowed_origins and not any(configured_frontend == o.rstrip('/') or configured_frontend.startswith(o.rstrip('/')) for o in allowed_origins):
            frontend_url = 'http://localhost:8100'
        else:
            frontend_url = configured_frontend

        reset_url = f"{frontend_url}/reset-password#token={raw_token}"
        minutes = current_app.config.get('PASSWORD_RESET_TOKEN_MINUTES', 20)

        subject = "Restablece tu contraseña en Afinia"

        text_body = (
            f"Hola,\n\n"
            f"Hemos recibido una solicitud para restablecer la contraseña de tu cuenta en Afinia.\n"
            f"Para ingresar una nueva contraseña, por favor ingresa al siguiente enlace:\n\n"
            f"{reset_url}\n\n"
            f"Este enlace tiene una vigencia temporal de {minutes} minutos y solo puede utilizarse una vez.\n\n"
            f"Si tú no solicitaste este cambio, puedes ignorar este mensaje de forma segura: "
            f"tu contraseña actual permanecerá sin modificaciones y tu cuenta seguirá protegida.\n\n"
            f"— El equipo de Afinia"
        )

        html_body = (
            f"<div style='font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;'>"
            f"<h2 style='color: #4A90E2;'>Restablecimiento de contraseña</h2>"
            f"<p>Hemos recibido una solicitud para restablecer la contraseña de tu cuenta en Afinia.</p>"
            f"<p>Para crear una nueva contraseña y recuperar tu acceso, haz clic en el siguiente botón:</p>"
            f"<p style='text-align: center; margin: 30px 0;'>"
            f"<a href='{reset_url}' style='background-color: #4A90E2; color: #fff; padding: 12px 24px; "
            f"text-decoration: none; border-radius: 6px; font-weight: bold;'>Restablecer mi contraseña</a>"
            f"</p>"
            f"<p style='font-size: 13px; color: #777;'>O copia y pega el siguiente enlace en tu navegador:<br>"
            f"<a href='{reset_url}' style='color: #4A90E2; word-break: break-all;'>{reset_url}</a></p>"
            f"<p style='font-size: 12px; color: #999; margin-top: 30px;'>"
            f"Este enlace expira en {minutes} minutos y es de un solo uso.<br>"
            f"Si tú no solicitaste restablecer tu contraseña, desestima este mensaje. Tu cuenta sigue segura."
            f"</p>"
            f"</div>"
        )

        backend = current_app.config.get('MAIL_BACKEND', 'in_memory').lower()

        if backend == 'in_memory':
            # Registro en memoria seguro para QA / pruebas automatizadas
            self._sent_messages.append({
                'type': 'password_reset',
                'to': normalized_email,
                'subject': subject,
                'reset_url': reset_url,
                'token': raw_token,
                'text_body': text_body,
                'html_body': html_body
            })
            current_app.logger.info(f"Correo de restablecimiento encolado en memoria para {normalized_email}")
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
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    if use_tls:
                        server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                current_app.logger.info(f"Correo de restablecimiento enviado vía SMTP a {normalized_email}")
            except Exception as e:
                current_app.logger.error(f"Error al enviar correo SMTP a {normalized_email}: {str(e)}")
                raise EmailDeliveryError(f"Error de transporte SMTP: {str(e)}")
        else:
            raise EmailDeliveryError(f"Backend de correo '{backend}' no reconocido.")

email_service = EmailService()
