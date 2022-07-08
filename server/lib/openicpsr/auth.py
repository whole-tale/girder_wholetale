import requests

from girder.exceptions import RestException
from ..verificator import Verificator


class OpenICPSRVerificator(Verificator):
    login_url = (
        "https://www.openicpsr.org/openicpsr/login"
        "?request_uri=https%3a%2f%2fwww.openicpsr.org%2fopenicpsr%2f&path=openICPSR"
    )

    @property
    def headers(self):
        if self.key:
            return {"JSESSIONID": self.key}
        return {}

    def verify(self):
        try:
            r = requests.get(self.login_url, cookies=self.headers)
            r.raise_for_status()
            assert r.url == "https://www.openicpsr.org/openicpsr/"
        except (AssertionError, requests.exceptions.HTTPError):
            raise RestException(
                f"Invalid password or expired session for '{self.resource_server}'"
            )

    def preauth(self, user):
        headers = {
            "Connection": "keep-alive",
            "DNT": "1",
            "Host": "www.icpsr.umich.edu",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": None,
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/102.0.0.0 Safari/537.36"
            ),
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Linux",
            "sec-gpc": "1",
        }

        oheaders = {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
                "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "DNT": "1",
            "Referer": "https://www.openicpsr.org/openicpsr/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/102.0.0.0 Safari/537.36"
            ),
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-gpc": "1",
        }

        with requests.Session() as session:
            # Get required session cookies
            req = session.get(
                "https://www.icpsr.umich.edu/mydata?path=ICPSR",
                headers=headers,
                allow_redirects=True,
            )
            req.raise_for_status()
            cookies = req.cookies

            headers.update(
                {
                    "Origin": "https://www.icpsr.umich.edu",
                    "Referer": "https://www.icpsr.umich.edu/rpxlogin",
                }
            )
            login_req = session.post(
                "https://www.icpsr.umich.edu/rpxlogin",
                headers=headers,
                cookies=cookies,
                files={
                    "email": (None, user["email"]),
                    "password": (None, self.key),
                    "path": (None, "ICPSR"),
                    "request_uri": (
                        None,
                        "https://www.icpsr.umich.edu/mydata?path=ICPSR",
                    ),
                    "noautoguest": (None, ""),
                    "Log In": (None, "Log In"),
                },
            )
            login_req.raise_for_status()
            cookies.update(login_req.cookies)
            req = session.get(
                "https://www.icpsr.umich.edu/mydata?path=ICPSR",
                headers=headers,
                cookies=cookies,
                allow_redirects=True,
            )
            req.raise_for_status()

            # OAUTH FLOW OpenICPSR <-> ICPSR
            r = session.get("https://www.openicpsr.org/")
            r.raise_for_status()
            cookies.update(r.cookies)  # get JSESSIONID

            data_req = session.get(self.login_url, headers=oheaders, cookies=cookies)
            data_req.raise_for_status()
            oauth_redir_url = data_req.headers.get("Refresh").split("URL=")[-1]
            oauth_redir_req = session.get(
                oauth_redir_url, headers=oheaders, cookies=cookies
            )
            oauth_redir_req.raise_for_status()
            try:
                callback_url = oauth_redir_req.headers.get("Refresh").split("URL=")[-1]
            except AttributeError:
                raise ValueError(f"Invalid password {self.key=} {user['email']=}")

            resp = session.get(
                callback_url, headers=oheaders, cookies=cookies
            )
            resp.raise_for_status()

            self.key = cookies["JSESSIONID"]
