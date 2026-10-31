#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/syscall.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
#include <string.h>
#include <fcntl.h>
static void __attribute__((noreturn)) fail(const char *s) {
 int saved=errno, fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);
 if(fd>=0) { dprintf(fd,"TB311FU arch-init: %s: %s\n",s,strerror(saved)); close(fd); }
 errno=saved; perror(s); sleep(10); execl("/bin/busybox","busybox","sh",NULL); for (;;) sleep(60);
}
static void bind(const char *a,const char *b) {
 struct stat st;
 if(stat(a,&st))fail(a);
 if(S_ISDIR(st.st_mode)) {
  char path[PATH_MAX];
  if(strlen(b)>=sizeof(path)) { errno=ENAMETOOLONG; fail(b); }
  strcpy(path,b);
  for(char *p=path+1;;p++) {
   if(*p=='/' || *p=='\0') {
    char saved=*p; *p='\0';
    if(mkdir(path,0755) && errno!=EEXIST)fail(path);
    *p=saved; if(!saved)break;
   }
  }
 }
 if(mount(a,b,NULL,MS_BIND,NULL))fail(b);
}
int main(void) {
 if(getpid()!=1) { fprintf(stderr,"PID 1 only\n"); return 1; }
 if(access("/arch/usr/lib/systemd/systemd",X_OK))fail("Arch systemd missing");
 if(mount(NULL,"/",NULL,MS_REC|MS_PRIVATE,NULL))fail("private root");
 bind("/arch","/arch");
 mkdir("/arch/.device-root",0700);
 if(chdir("/arch"))fail("chdir");
 if(syscall(SYS_pivot_root,".",".device-root"))fail("pivot_root");
 if(chdir("/"))fail("chdir root");
 const char *dirs[]={"dev","proc","sys","run",NULL};
 for(int i=0;dirs[i];i++) { char a[128],b[128];snprintf(a,sizeof(a),"/.device-root/%s",dirs[i]);snprintf(b,sizeof(b),"/%s",dirs[i]);if(mount(a,b,NULL,MS_MOVE,NULL))fail(b); }
 bind("/.device-root/home","/home");
 bind("/.device-root/lib/modules","/usr/lib/modules");
 bind("/.device-root/lib/firmware/postmarketos","/usr/lib/firmware/postmarketos");
 bind("/.device-root/vendor","/vendor");
 bind("/.device-root/boot","/boot");
 bind("/.device-root/var/lib/waydroid","/var/lib/waydroid");
 bind("/.device-root/etc/waydroid-extra","/etc/waydroid-extra");
 setenv("PATH","/usr/local/sbin:/usr/local/bin:/usr/bin",1);
 setenv("SYSTEMD_LOG_TARGET","kmsg",1);
 execl("/usr/lib/systemd/systemd","/sbin/init",NULL);fail("systemd");
}
