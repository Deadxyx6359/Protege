.pragma library
.import "pixel.js" as P

// The Far Station: a quiet lunar foreground looking toward a lensing disk.
// Light comes from the upper right. Sparse warm station lights are the only
// exception to a blue-grey palette, and the centre is left open for the UI.
function listener(p) {
    // A tiny, nearly black silhouette *inside* the event horizon. The front
    // accretion arc is painted afterward and hides the ends of its limbs.
    // No bright eyes or appearance/disappearance: the discovery is in looking.
    var shade="#0b121b", rim="#101923";
    p.poly([[370,72],[373,75],[374,80],[373,85],[370,87],[368,82],[369,77]],shade);
    var limbs=[[[369,79],[365,78],[363,74],[364,71]],
               [[373,79],[377,77],[379,73],[378,70]],
               [[370,85],[366,88],[363,88],[360,85]],
               [[372,85],[377,87],[380,85],[383,85]],
               [[370,86],[368,91],[370,95]],
               [[372,86],[375,92],[374,95]]];
    for(var i=0;i<limbs.length;i++) for(var j=0;j<limbs[i].length-1;j++) {
        var a=limbs[i][j],b=limbs[i][j+1];
        p.line(a[0],a[1],b[0],b[1],shade);
    }
    p.line(373,76,374,80,rim);
    p.dot(372,78,"#27333d");
}

function surveySatellite(p) {
    p.poly([[161,38],[168,39],[167,43],[160,42]],"#263b4d");
    p.poly([[176,40],[183,41],[182,45],[175,44]],"#263b4d");
    p.line(162,39,167,40,"#435666");p.line(177,41,182,42,"#435666");
    p.line(166,41,177,43,"#63737d");
    p.rect(169,40,5,5,"#465864");p.rect(173,40,1,4,"#91a0a3");
    p.line(172,40,175,36,"#526977");p.dot(175,35,"#7d9098");
}

function paint(ctx, frame) {
    var p=new P.Painter(ctx), f=frame||0;
    for(var y=0;y<270;y++) p.rect(0,y,480,1,P.mix("#060c18","#15232f",Math.floor(y/24)/15));
    /*  A broken, very low-contrast dust lane: broad structure, no scrolling fog.

        The lane is drawn before the black hole, so it is behind it — but the
        accretion disk is a ring of single pixels, not a solid, and the dust
        showed straight through the gaps. Since the lane's own path
        (152 - 0.21x) passes within a few pixels of the hole at x=371, the two
        were interleaving and the disk read as broken.

        Clearing a radius around the horizon fixes the layering and earns its
        keep: a black hole that has swept its own neighbourhood clear of dust
        is what one would actually look like.  */
    var voidX=371, voidY=83, voidR=86;
    for(var dust=0;dust<330;dust++) {
        var dx=P.hash(dust*5+737)*480;
        var dy=152-dx*0.21+(P.hash(dust*9+355)-0.5)*32;
        var radius=2+P.hash(dust+919)*9;
        var gx=(dx-voidX), gy=(dy-voidY)*1.9;
        if(gx*gx+gy*gy < voidR*voidR) continue;
        p.ellipse(dx,dy,radius,radius*0.38,dust%3===0?"#12202d":"#101b28");
    }
    for(var star=0;star<230;star++) {
        var sx=Math.floor(P.hash(star*3+3)*480), sy=Math.floor(P.hash(star*7+97)*245);
        // The event horizon clears its own part of the sky later in the paint.
        var color=["#293847","#40505e","#687980","#8d9ca0"][star%4];
        if(star%23===0) color=["#71858d","#94a6ac","#bec7c7","#94a6ac"][f];
        p.dot(sx,sy,color);
        if(star%61===0) {
            p.rect(sx-1,sy,3,1,"#aab8b9");p.rect(sx,sy-1,1,3,"#7b8f96");
        }
    }
    // A distant cold moon, with a broken terminator and one crater.
    p.ellipse(257,35,8,8,"#384852");
    p.ellipse(255,34,7,7,"#70828b");
    p.ellipse(260,37,7,8,"#15222e");
    p.ellipse(253,31,2,1,"#435b67");p.dot(252,32,"#81949a");
    surveySatellite(p);
    // A faint, fixed comet and a handful of lit debris at the edge of the view.
    p.line(203,18,219,13,"#192b3b");p.line(212,15,219,13,"#344c5c");p.dot(220,13,"#869aa1");
    for(var rock=0;rock<7;rock++) {
        var ax=9+rock*5,ay=115+rock*3+P.hash(rock+785)*5;
        p.ellipse(ax,ay,1+rock%2,1,"#263b49");p.dot(ax+1,ay-1,"#455a65");
    }
    // Neutron star: restrained bipolar jets and a four-step breathing core.
    var pulse=["#8ea5af","#a8bdc4","#cbdadd","#a8bdc4"][f];
    p.line(71,48,89,79,"#263c50");p.line(69,46,78,61,"#1b2e40");
    p.line(85,70,94,85,"#1b2e40");
    p.ellipse(81,65,6,4,"#172d3e");p.ellipse(81,65,4,2,"#35566a");
    p.line(75,67,88,63,"#516d80");p.rect(80,64,2,2,pulse);
    // Lensing around the black hole. Disks are deliberately eccentric so the
    // lower arc reads as the front of the same tilted disk, not a Saturn ring.
    var hx=371, hy=83;
    p.ellipse(hx,hy,41,35,"#101d29");
    p.ellipse(hx,hy,32,30,"#192b37");
    p.ellipse(hx,hy,28,27,"#314653");
    p.ellipse(hx,hy,25,25,"#7b8f98");
    p.ellipse(hx,hy+2,24,24,"#0a111b");
    // Thin disk follows an inclined elliptical orbit and has a warmer inner rim.
    for(var ring=0;ring<5;ring++) {
        var radius=67-ring*5;
        for(var a=0;a<360;a+=1) {
            var theta=a*Math.PI/180;
            var ox=Math.cos(theta)*radius, oy=Math.sin(theta)*(11-ring*0.9)-ox*0.18;
            if(oy>0) continue;
            p.dot(hx+ox,hy+oy,["#263945","#405863","#6d8289","#9caeae","#c1c9c0"][ring]);
        }
    }
    p.ellipse(hx,hy+1,22,22,"#040911");
    listener(p);
    for(var r=0;r<6;r++) {
        var rad=68-r*5;
        for(var angle=0;angle<180;angle+=1) {
            var t=angle*Math.PI/180;
            var rx=Math.cos(t)*rad, ry=Math.sin(t)*(11-r*0.7)-rx*0.18;
            p.dot(hx+rx,hy+ry,["#243944","#405965","#627b86","#94a8ab","#c4cfca","#dee0cd"][r]);
        }
    }
    // Four dim knots travel a few pixels within the disk, never across the sky.
    for(var knot=0;knot<4;knot++) {
        var kx=hx-43+knot*25+[0,2,3,2][f], ky=hy+8-(kx-hx)*0.18;
        p.rect(kx,ky,3,1,"#a9babc");
    }
    // Large foreground crescent. Sphere normals create broad quantized planes;
    // terrain marks are clipped to the lit limb, with no transparent circles.
    var cx=29,cy=266,rr=112;
    var sphere=["#101c28","#1e303e","#304856","#48616d","#6b8188","#93a4a5"];
    for(var py=153;py<270;py++) {
        var first=-1, lastColor="";
        for(var px=0;px<=143;px++) {
            var nx=(px-cx)/rr,ny=(py-cy)/rr,d=nx*nx+ny*ny;
            var col="";
            if(d<=1) {
                var nz=Math.sqrt(1-d), illumination=nx*0.53-ny*0.54-nz*0.38;
                var level=Math.max(0,Math.min(5,Math.floor((illumination+0.1)*7)));
                col=sphere[level];
                if(d>0.976 && level>2) col="#a7b5b2";
                if(level>1 && P.hash(px*5+py*479)>0.965) col=sphere[Math.max(0,level-1)];
            }
            if(col!==lastColor) {
                if(lastColor) p.rect(first,py,px-first,1,lastColor);
                first=px;lastColor=col;
            }
        }
        if(lastColor) p.rect(first,py,144-first,1,lastColor);
    }
    // Craters are placed on the visible upper hemisphere, in the same light.
    var craters=[[32,170,9,3],[75,187,13,6],[104,215,8,6],[12,193,16,6],[55,215,6,3]];
    for(var crater=0;crater<craters.length;crater++) {
        var q=craters[crater];
        p.ellipse(q[0],q[1],q[2],q[3],"#647c85");
        p.ellipse(q[0]-1,q[1]+1,q[2]-1,q[3]-1,"#2f4656");
        p.line(q[0]-q[2]*0.5,q[1]-q[3],q[0]+q[2]*0.5,q[1]-q[3],"#8ea2a8");
    }
    // A solitary rectangular ruin on the sunward crater rim, with a short
    // leftward shadow. It is deliberately too small to explain itself.
    p.line(103,215,98,216,"#243746");
    p.poly([[103,215],[103,208],[105,207],[106,214]],"#1a2b38");
    p.line(105,208,106,214,"#4d626d");
    // A remote ringed planet is tucked into the lower sky.
    p.line(212,180,244,168,"#314854");p.line(214,181,246,169,"#516b76");
    p.ellipse(229,175,8,8,"#566d79");
    p.rect(223,171,12,1,"#7c8e95");p.rect(224,177,10,1,"#394e60");
    p.ellipse(232,177,6,7,"#1e3040");p.line(214,183,246,171,"#69818a");
    // Foreground ridge creates a place from which to see the sky.
    p.poly([[229,270],[280,251],[305,251],[324,237],[349,242],[378,226],
            [409,230],[435,213],[463,221],[480,216],[480,270]],"#172634");
    p.poly([[277,270],[318,252],[345,254],[375,239],[404,244],[431,230],
            [459,236],[480,228],[480,270]],"#0b1622");
    p.poly([[375,239],[405,239],[434,219],[459,227],[438,225],[413,244]],"#2c404b");
    p.line(435,214,449,218,"#596d76");
    p.line(325,237,346,242,"#364c57");
    // Radio telescope and habitation module on a level rock shelf.
    p.rect(373,242,35,2,"#263b48");
    p.poly([[386,241],[391,225],[394,225],[399,241]],"#3d5361");
    p.poly([[390,241],[392,228],[396,241]],"#101c29");
    p.line(391,227,398,218,"#6c818a",2);
    p.poly([[379,207],[383,222],[390,226],[398,223],[406,216]],"#536d7c");
    p.poly([[379,207],[386,216],[399,221],[406,216]],"#8fa1a5");
    p.line(379,207,406,216,"#bcc8c5");
    p.line(385,219,396,206,"#718992");p.line(403,220,396,206,"#526f80");
    p.rect(396,204,2,3,"#9faaa9");
    p.rect(420,234,23,12,"#2a3e4c");p.rect(417,232,27,3,"#435b68");
    p.rect(423,237,5,3,"#c0a77d");p.rect(432,237,5,3,"#c0a77d");
    p.rect(439,238,3,8,"#111c28");
    p.line(437,232,437,220,"#516976");p.dot(437,219,["#8a8e80","#8a8e80","#baa585","#8a8e80"][f]);
    // Observatory equipment is planted on the shelf rather than orbiting it.
    p.line(355,247,355,254,"#3b515e");p.line(354,254,348,255,"#08131e");
    p.poly([[346,238],[365,242],[362,248],[343,244]],"#2c4558");
    p.line(346,238,365,242,"#627c8b");
    p.line(344,241,363,245,"#142736");
    for(var grid=0;grid<3;grid++) p.line(350+grid*4,240+grid,348+grid*4,245+grid,"#142736");
    // A small visitor, easy to miss. The hull stays fixed; one navigation light breathes.
    p.ellipse(319,199,3,2,"#496b78");p.ellipse(319,202,8,2,"#728e95");
    p.rect(313,203,12,1,"#344c5b");
    p.dot(316,203,f===2?"#abc8bc":"#6b938d");p.dot(322,203,"#769792");
    for(var stone=0;stone<65;stone++) {
        var xx=285+P.hash(stone*7+432)*195, yy=253+P.hash(stone*11+808)*17;
        p.rect(xx,yy,1+P.hash(stone)*4,1,stone%3===0?"#293f4c":"#172837");
    }
    // A parked rover, a helmet glint, and a path of prints are small enough to
    // stay secondary to the sky, but make the observatory feel inhabited.
    p.ellipse(329,262,8,1,"#07121d");
    p.rect(325,257,11,3,"#3d5260");p.rect(330,255,5,3,"#5c707a");
    p.rect(333,256,2,1,"#a1b1b4");p.rect(326,260,2,2,"#1a2b39");p.rect(333,260,2,2,"#1a2b39");
    p.line(327,256,327,251,"#425c6c");p.dot(327,250,"#7c939f");
    for(var step=0;step<6;step++) {
        p.dot(440+step*2,248+step%2,"#344b57");p.dot(441+step*2,250+step%2,"#344b57");
    }
    p.ellipse(450,253,3,1,"#07121d");p.rect(451,246,2,5,"#5c737e");
    p.ellipse(452,244,2,2,"#71868e");p.rect(452,243,2,1,"#adc0be");
    p.dot(451,252,"#455e6d");p.dot(454,252,"#455e6d");
}
