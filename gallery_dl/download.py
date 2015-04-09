# -*- coding: utf-8 -*-

# Copyright 2015 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

import os
import sys
import re
import importlib

from .extractor.common import Message

class DownloadManager():

    def __init__(self, opts, config):
        self.opts = opts
        self.config = config
        self.modules = {}
        self.extractors = ExtractorFinder(config)

    def add(self, url):
        job = DownloadJob(self, url)
        job.run()

    def get_downloader_module(self, scheme):
        """Return a downloader module suitable for 'scheme'"""
        module = self.modules.get(scheme)
        if module is None:
            module = importlib.import_module(".downloader."+scheme, __package__)
            self.modules[scheme] = module
        return module

    def get_base_directory(self):
        if self.opts.dest:
            return self.opts.dest
        else:
            return self.config.get("general", "destination", fallback="/tmp/")


class DownloadJob():

    def __init__(self, mngr, url):
        self.mngr = mngr
        self.extractor, self.info = mngr.extractors.get_for_url(url)
        self.directory = mngr.get_base_directory()
        self.downloaders = {}
        self.filename_fmt = mngr.config.get(
            self.info["category"], "filename",
            fallback=self.info["filename"]
        )
        try:
            segments = mngr.config.get(
                self.info["category"], "directory"
            ).split("/")
        except Exception:
            segments = self.info["directory"]
        self.directory_fmt = os.path.join(*segments)

    def run(self):
        """Execute/Run the downlaod job"""
        if self.extractor is None:
            return # TODO: error msg

        for msg in self.extractor:
            if msg[0] == Message.Url:
                self.download(msg)

            elif msg[0] == Message.Headers:
                self.get_downloader("http:").set_headers(msg[1])

            elif msg[0] == Message.Cookies:
                self.get_downloader("http:").set_cookies(msg[1])

            elif msg[0] == Message.Directory:
                self.set_directory(msg)

            elif msg[0] == Message.Version:
                if msg[1] != 1:
                    raise "unsupported message-version ({}, {})".format(
                        self.info.category, msg[1]
                    )
                # TODO: support for multiple message versions

    def download(self, msg):
        """Download the resource specified in 'msg'"""
        _, url, metadata = msg
        filename = self.filename_fmt.format(**metadata)
        path = os.path.join(self.directory, filename)
        if os.path.exists(path):
            self.print_skip(path)
            return
        downloader = self.get_downloader(url)
        self.print_start(path)
        tries = downloader.download(url, path)
        self.print_success(path, tries)

    def set_directory(self, msg):
        """Set and create the target directory for downloads"""
        self.directory = os.path.join(
            self.mngr.get_base_directory(),
            self.directory_fmt.format(**msg[1])
        )
        os.makedirs(self.directory, exist_ok=True)

    def get_downloader(self, url):
        """Return, and possibly construct, a downloader suitable for 'url'"""
        pos = url.find(":")
        scheme = url[:pos] if pos != -1 else "http"
        if scheme == "https":
            scheme = "http"

        downloader = self.downloaders.get(scheme)
        if downloader is None:
            module = self.mngr.get_downloader_module(scheme)
            downloader = module.Downloader(self.extractor)
            self.downloaders[scheme] = downloader

        return downloader

    @staticmethod
    def print_start(path):
        print(path, end="")
        sys.stdout.flush()

    @staticmethod
    def print_skip(path):
        print("\033[2m", path, "\033[0m", sep="")

    @staticmethod
    def print_success(path, tries):
        if tries == 0:
            print("\r", end="")
        print("\r\033[1;32m", path, "\033[0m", sep="")


class ExtractorFinder():

    def __init__(self, config):
        self.config = config

    def get_for_url(self, url):
        name, match = self.find_pattern_match(url)
        if match:
            module = importlib.import_module(".extractor." + name, __package__)
            klass = getattr(module, module.info["extractor"])
            return klass(match, self.config), module.info
        else:
            print("pattern mismatch")
            return None

    def find_pattern_match(self, url):
        for category in self.config:
            for key, value in self.config[category].items():
                if key.startswith("regex"):
                    print(value)
                    match = re.match(value, url)
                    if match:
                        return category, match
        for name, info in self.extractor_metadata():
            for pattern in info["pattern"]:
                print(pattern)
                match = re.match(pattern, url)
                if match:
                    return name, match
        return None, None

    def extractor_metadata(self):
        path = os.path.join(os.path.dirname(__file__), "extractor")
        for name in os.listdir(path):
            extractor_path = os.path.join(path, name)
            info = self.get_info_dict(extractor_path)
            if info is not None:
                yield os.path.splitext(name)[0], info

    @staticmethod
    def get_info_dict(extractor_path):
        try:
            with open(extractor_path) as file:
                for _ in range(30):
                    line = next(file)
                    if line.startswith("info ="):
                        break
                else:
                    return None

                info = [line[6:]]
                for line in file:
                    info.append(line)
                    if line.startswith("}"):
                        break
        except (StopIteration, OSError):
            return None
        return eval("".join(info))