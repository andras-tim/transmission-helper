#!/usr/bin/env python3
import json
import mimetypes
import os
import smtplib
import transmissionrpc
from email import encoders
from email.mime.audio import MIMEAudio
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
from pwd import getpwuid


class TransmissionHelper:
    def __init__(self):
        self.config = self.__get_config()
        self.rpc = self.__connect_to_transmission()

    def __get_config(self) -> dict:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as fd:
            return json.load(fd)

    def __connect_to_transmission(self) -> transmissionrpc.Client:
        return transmissionrpc.Client(
            address=self.config['transmissionRpc']['host'],
            port=self.config['transmissionRpc']['port'] or transmissionrpc.DEFAULT_PORT,
            user=self.config['transmissionRpc']['username'],
            password=self.config['transmissionRpc']['password'],
        )

    def check_new_torrents(self):
        for root, dirs, files in os.walk(self.config['newTorrents']['watchPath']):
            for file in files:
                if file.endswith('.torrent'):
                    path = os.path.join(root, file)
                    self.__handle_new_torrent_file(path)
        return self

    def __handle_new_torrent_file(self, torrent_path: str):
        try:
            self.rpc.add_torrent('file://{}'.format(torrent_path))
        except transmissionrpc.error.TransmissionError:
            os.rename(torrent_path, '{}.error'.format(torrent_path))
            return
        self.__send_torrent_by_email(torrent_path)
        os.remove(torrent_path)

    def __send_torrent_by_email(self, torrent_path: str):
        text = 'Uploaded by {}'.format(getpwuid(os.stat(torrent_path).st_uid).pw_name)

        mail_sender = MailSender(
            host=self.config['emailDelivery']['host'],
            port=self.config['emailDelivery']['port']
        )
        mail_sender.send_mail(
            send_from=self.config['newTorrents']['emailSender'],
            send_to=self.config['newTorrents']['emailRecipients'],
            subject=self.config['newTorrents']['emailSubject'],
            torrent_path=torrent_path,
            text=text
        )

    def check_completed_torrents(self):
        torrents = self.rpc.get_torrents()
        for torrent in torrents:
            if torrent.doneDate:
                self.__handle_done_torrent(torrent)
        return self

    def __handle_done_torrent(self, torrent):
        self.rpc.remove_torrent(torrent.id, delete_data=False)


class MailSender:
    def __init__(self, host: str, port: int):
        self.smtp = smtplib.SMTP(host, port)

    def send_mail(self, send_from: str, send_to: list, subject: str, torrent_path: str, text: str=''):
        torrent_name = os.path.basename(torrent_path)

        container = MIMEMultipart()
        container['From'] = send_from
        container['To'] = COMMASPACE.join(send_to)
        container['Subject'] = subject.format(torrent=torrent_name)
        container['Date'] = formatdate(localtime=True)
        container.preamble = 'You will not see this in a MIME-aware mail reader.\n'

        message_attachment = self.__make_attachment(torrent_path)
        container.attach(message_attachment)

        if text:
            container.attach(MIMEText(text))

        composed_message = container.as_string()

        self.smtp.sendmail(send_from, send_to, composed_message)
        self.smtp.close()

    def __make_attachment(self, file_path: str) -> MIMEBase:
        file_name = os.path.basename(file_path)
        maintype, subtype = self.__get_mime_type_and_subtype(file_path)

        with open(file_path) as fp:
            if maintype == 'text':
                message_part = MIMEText(fp.read(), _subtype=subtype)
            elif maintype == 'image':
                message_part = MIMEImage(fp.read(), _subtype=subtype)
            elif maintype == 'audio':
                message_part = MIMEAudio(fp.read(), _subtype=subtype)
            else:
                message_part = MIMEBase(maintype, subtype)
                message_part.set_payload(fp.read())
                encoders.encode_base64(message_part)
            message_part.add_header('Content-Disposition', 'attachment', filename=file_name)

        return message_part

    def __get_mime_type_and_subtype(self, file_path) -> tuple:
        ctype, encoding = mimetypes.guess_type(file_path)
        if ctype is None or encoding is not None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)

        return maintype, subtype


if __name__ == '__main__':
    TransmissionHelper(). \
        check_new_torrents(). \
        check_completed_torrents()
